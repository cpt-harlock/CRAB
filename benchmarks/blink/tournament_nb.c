#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <signal.h>
#include <stdbool.h>
#include <sched.h>
#include "common.h"

/* Tournament bandwidth (non-blocking, windowed full-duplex).
 *
 * Over w_size-1 rounds every rank is paired with every other rank exactly
 * once (round-robin "circle" method). Each pairing runs a windowed full-duplex
 * exchange: the lower rank acts as sender, the higher as receiver, both posting
 * a window of outstanding Isend/Irecv in each direction. The window is guarded
 * by a per-window timeout and closed by a small ack that re-synchronizes the
 * pair every iteration. Throughput basis per exchange is window*msg_size*2. */

#define TAG_DATA_FWD 100 /* sender -> receiver payload */
#define TAG_ACK      101 /* receiver -> sender window ack */
#define TAG_DATA_BWD 102 /* receiver -> sender payload */

/*wait for all requests to complete, bailing out after timeout_seconds*/
static int check_with_timeout(int count, int timeout_seconds, MPI_Request *reqs) {
    int completed = 0;
    int index;
    int flag;
    double start_time = MPI_Wtime();
    while (completed < count) {
        MPI_Testany(count, reqs, &index, &flag, MPI_STATUS_IGNORE);
        if (flag) {
            completed++;
        }
        if (MPI_Wtime() - start_time > timeout_seconds) {
            return -1; /*timeout*/
        }
    }
    return 0; /*all requests completed*/
}

/*cancel and reap any still-pending requests (cold path, after a timeout)*/
static void drain_requests(int count, MPI_Request *reqs) {
    int i;
    for (i = 0; i < count; i++) {
        if (reqs[i] != MPI_REQUEST_NULL) {
            MPI_Cancel(&reqs[i]);
            MPI_Wait(&reqs[i], MPI_STATUS_IGNORE);
        }
    }
}

/*one windowed full-duplex exchange with a partner; returns 1 on timeout*/
static int exchange_window(int role, int partner, unsigned char *send_buf,
                           unsigned char *recv_buf, int window, int msg_size,
                           int timeout, MPI_Request *reqs) {
    int j;
    if (role == 0) { /*sender: send TAG_DATA_FWD, receive TAG_DATA_BWD*/
        for (j = 0; j < window; j++) {
            MPI_Isend(send_buf, msg_size, MPI_BYTE, partner, TAG_DATA_FWD,
                      MPI_COMM_WORLD, &reqs[j]);
            MPI_Irecv(recv_buf, msg_size, MPI_BYTE, partner, TAG_DATA_BWD,
                      MPI_COMM_WORLD, &reqs[window + j]);
        }
    } else { /*receiver: receive TAG_DATA_FWD, send TAG_DATA_BWD*/
        for (j = 0; j < window; j++) {
            MPI_Irecv(recv_buf, msg_size, MPI_BYTE, partner, TAG_DATA_FWD,
                      MPI_COMM_WORLD, &reqs[j]);
            MPI_Isend(send_buf, msg_size, MPI_BYTE, partner, TAG_DATA_BWD,
                      MPI_COMM_WORLD, &reqs[window + j]);
        }
    }

    int timed_out = (check_with_timeout(window * 2, timeout, reqs) == -1);
    if (timed_out) {
        drain_requests(window * 2, reqs);
    }

    /*ack handshake re-synchronizes the pair at the end of each window*/
    unsigned char ack[4] = {'a', 'c', 'k', 0};
    if (role == 0) {
        MPI_Recv(ack, 4, MPI_BYTE, partner, TAG_ACK, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    } else {
        MPI_Send(ack, 4, MPI_BYTE, partner, TAG_ACK, MPI_COMM_WORLD);
    }
    return timed_out ? 1 : 0;
}

/*pair arr[i] with arr[n-1-i] into partner[] (circle method, current rotation)*/
static void tournament_round(const int *arr, int *partner, int n) {
    int i;
    for (i = 0; i < n / 2; i++) {
        int a = arr[i];
        int b = arr[n - 1 - i];
        partner[a] = b;
        partner[b] = a;
    }
}

/*rotate positions 1..n-1, keeping position 0 fixed, for the next round*/
static void rotate_arr(int *arr, int n) {
    int i;
    int tmp = arr[n - 1];
    for (i = n - 1; i > 1; i--) {
        arr[i] = arr[i - 1];
    }
    arr[1] = tmp;
}

int main(int argc, char** argv){

    /*init MPI world*/
    MPI_Init(&argc,&argv);
    MPI_Comm_size(MPI_COMM_WORLD, &w_size);
    MPI_Comm_rank(MPI_COMM_WORLD, &my_rank);

    /*register signal handler*/
    signal(SIGUSR1,sig_handler); //or SIGUSR1 here

    /*default values*/
    int master_rank=0;
    bool master_rand=false;

    int rand_seed=1;

    int msg_size=4194304;
    int measure_granularity=1;
    max_samples=1000;

    int skip_iters=2;
    int max_iters=20;
    bool endless=false;

    int window=64;
    int timeout=1;
    int num_rounds=0; /*0 -> all w_size-1 rounds*/

    double burst_length=0.0;
    bool burst_length_rand=false;
    double burst_pause=0.0;
    bool burst_pause_rand=false;

    int i,k,s,g,round;

    /*read cmd line args*/
    for(i=1;i<argc;i++){
        if(strcmp(argv[i],"-mrank")==0){
            ++i;
            master_rank=atoi(argv[i]);
        }else if(strcmp(argv[i],"-mrand")==0){
            master_rand=true;
        }else if(strcmp(argv[i],"-msgsize")==0){
            ++i;
            msg_size=atoi(argv[i]);
        }else if(strcmp(argv[i],"-window")==0){
            ++i;
            window=atoi(argv[i]);
        }else if(strcmp(argv[i],"-timeout")==0){
            ++i;
            timeout=atoi(argv[i]);
        }else if(strcmp(argv[i],"-rounds")==0){
            ++i;
            num_rounds=atoi(argv[i]);
        }else if(strcmp(argv[i],"-endl")==0){
            endless=true;
        }else if(strcmp(argv[i],"-iter")==0){
            ++i;
            max_iters=atoi(argv[i]);
        }else if(strcmp(argv[i],"-warmup")==0){
            ++i;
            skip_iters=atoi(argv[i]);
        }else if(strcmp(argv[i],"-blength")==0){
            ++i;
            burst_length=atof(argv[i]);
        }else if(strcmp(argv[i],"-bpause")==0){
            ++i;
            burst_pause=atof(argv[i]);
        }else if(strcmp(argv[i],"-bprand")==0){
            burst_pause_rand=true;
        }else if(strcmp(argv[i],"-blrand")==0){
            burst_length_rand=true;
        }else if(strcmp(argv[i],"-seed")==0){
            ++i;
            rand_seed=atoi(argv[i]);
        }else if(strcmp(argv[i],"-grty")==0){
            ++i;
            measure_granularity=atoi(argv[i]);
        }else if(strcmp(argv[i],"-maxsamples")==0){
            ++i;
            max_samples=atoi(argv[i]);
        }else{
            if(my_rank==master_rank){
                fprintf(stderr, "Unknown argument: %s\n", argv[i]);
                exit(-1);
            }
        }
    }
    /*set seed such that all ranks share rands*/
    srand(rand_seed);

    /*randomized master rank*/
    if(master_rand){
        master_rank=rand()%w_size;
    }

    if(window<1){
        if(my_rank==master_rank){
            fprintf(stderr,"Window size must be greater than 0\n");
        }
        exit(-1);
    }
    if(timeout<0){
        if(my_rank==master_rank){
            fprintf(stderr,"Timeout must be non-negative\n");
        }
        exit(-1);
    }
    if(w_size%2==1){
        if(my_rank==master_rank){
            fprintf(stderr,"Tournament needs an even number of ranks\n");
        }
        exit(-1);
    }

    /*all w_size-1 rounds by default; -rounds may cap (but not exceed) them*/
    if(num_rounds<=0 || num_rounds>w_size-1){
        num_rounds=w_size-1;
    }

    /*write_results() treats the leading warm_up_iters samples of the gathered
      series as warmup; here warmup is per pairing (skip_iters) and those
      iterations are never recorded, so keep the global series warmup at 0.*/
    warm_up_iters=0;

    /*pin to core*/
    /*cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(1, &mask);
    sched_setaffinity(0, sizeof(mask), &mask);*/

    /*allocate buffers*/
    int send_buf_size, recv_buf_size;
    unsigned char *send_buf;
    unsigned char *recv_buf;
    int *arr;
    int *partner;
    MPI_Request *reqs;

    send_buf_size=msg_size;
    recv_buf_size=msg_size; /*the window reuses a single recv buffer*/

    send_buf=(unsigned char*)malloc_align(send_buf_size);
    recv_buf=(unsigned char*)malloc_align(recv_buf_size);
    arr=(int*)malloc_align(sizeof(int)*w_size);
    partner=(int*)malloc_align(sizeof(int)*w_size);
    reqs=(MPI_Request*)malloc_align(sizeof(MPI_Request)*window*2);
    durations=(double *)malloc_align(sizeof(double)*max_samples);

    if(send_buf==NULL || recv_buf==NULL || arr==NULL || partner==NULL || reqs==NULL || durations==NULL){
        fprintf(stderr,"Failed to allocate a buffer on rank %d\n",my_rank);
        exit(-1);
    }

    /*fill send buffer with dummies*/
    for(i=0;i<send_buf_size;i++){
        send_buf[i]='a';
    }

    /*print basic info to stdout*/
    if(my_rank==master_rank){
        double bytes_per_exchange=(double)window*msg_size*2.0;
        if(endless){
            printf("Tournament with %d processes, msg-size: %d, window: %d, rounds: %d, "
                    "timeout: %ds, bytes/exchange: %.0f, test iterations: endless.\n"
                    ,w_size,msg_size,window,num_rounds,timeout,bytes_per_exchange);
        }else{
            printf("Tournament with %d processes, msg-size: %d, window: %d, rounds: %d, "
                    "timeout: %ds, bytes/exchange: %.0f, test iterations: %d.\n"
                    ,w_size,msg_size,window,num_rounds,timeout,bytes_per_exchange,max_iters);
        }
    }

    /*measured iterations*/
    double burst_start_time;
    double measure_start_time;
    double burst_length_mean=burst_length;
    double burst_pause_mean=burst_pause;
    bool burst_cont=false;
    int timeouts=0;
    curr_iters=0;

    MPI_Barrier(MPI_COMM_WORLD);
    do{
        /*fresh tournament schedule for every full pass*/
        for(i=0;i<w_size;i++){
            arr[i]=i;
        }
        for(round=0;round<num_rounds;round++){
            tournament_round(arr,partner,w_size);
            int partner_rank=partner[my_rank];
            int role=(my_rank<partner_rank)?0:1; /*0 sender, 1 receiver*/

            MPI_Barrier(MPI_COMM_WORLD); /*sync before this pairing*/

            /*per-pairing warmup, never recorded*/
            for(s=0;s<skip_iters;s++){
                exchange_window(role,partner_rank,send_buf,recv_buf,window,msg_size,timeout,reqs);
            }

            for(k=0;k<max_iters;k++){
                if(burst_length_rand){ /*randomized burst length*/
                    burst_length=rand_expo(burst_length_mean);
                }
                burst_start_time=MPI_Wtime();
                do{
                    MPI_Barrier(MPI_COMM_WORLD);
                    measure_start_time=MPI_Wtime();
                    for(g=0;g<measure_granularity;g++){
                        if(exchange_window(role,partner_rank,send_buf,recv_buf,window,msg_size,timeout,reqs)){
                            timeouts++;
                        }
                    }
                    durations[curr_iters%max_samples]=MPI_Wtime()-measure_start_time; /*write result to buffer (lru space)*/
                    curr_iters++;
                    if(burst_length!=0){ /*bcast needed for synch if bursts timed*/
                        if(my_rank==master_rank){ /*master decides if burst should be continued*/
                            burst_cont=((MPI_Wtime()-burst_start_time)<burst_length);
                        }
                        MPI_Bcast(&burst_cont,1,MPI_INT,master_rank,MPI_COMM_WORLD); /*bcast the masters decision*/
                    }
                }while(burst_cont);
                if(burst_pause!=0){
                    if(burst_pause_rand){ /*randomized break length*/
                        burst_pause=rand_expo(burst_pause_mean);
                    }
                    dsleep(burst_pause);
                }
            }
            rotate_arr(arr,w_size); /*advance schedule for the next round*/
        }
    }while(endless);

    /*write results to file*/
    MPI_Barrier(MPI_COMM_WORLD);
    write_results();

    /*report window timeouts across all ranks (stderr: stdout is parsed as CSV)*/
    int total_timeouts=0;
    MPI_Reduce(&timeouts,&total_timeouts,1,MPI_INT,MPI_SUM,master_rank,MPI_COMM_WORLD);
    if(my_rank==master_rank && total_timeouts>0){
        fprintf(stderr,"Total window timeouts: %d\n",total_timeouts);
        fflush(stderr);
    }

    /*free allocated buffers*/
    free(durations);
    free(reqs);
    free(partner);
    free(arr);
    free(recv_buf);
    free(send_buf);

    /*exit MPI library*/
    MPI_Finalize();
}
