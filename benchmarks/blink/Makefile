# Directories
SRC_DIR = .
BIN_DIR = bin

# Source files
C_SRCS   = $(wildcard $(SRC_DIR)/*.c)
CPP_SRCS = $(wildcard $(SRC_DIR)/*.cpp)
SRCS     = $(C_SRCS) $(CPP_SRCS)

# Executable names
BINS = $(patsubst $(SRC_DIR)/%.c, $(BIN_DIR)/%, $(C_SRCS))
BINS += $(patsubst $(SRC_DIR)/%.cpp, $(BIN_DIR)/%, $(CPP_SRCS))

# Flags
CFLAGS   = -lm -D_GNU_SOURCE -O3
CXXFLAGS = -lm -D_GNU_SOURCE -O3 -std=c++17

# Build all binaries
all: $(BINS)

# Rule for .c → executable
$(BIN_DIR)/%: $(SRC_DIR)/%.c $(SRC_DIR)/common.h $(SRC_DIR)/results.h
	mpicc -o $@ $< $(CFLAGS)

# Rule for .cpp → executable
$(BIN_DIR)/%: $(SRC_DIR)/%.cpp $(SRC_DIR)/common.h $(SRC_DIR)/results.h
	mpicxx -o $@ $< $(CXXFLAGS)

clean:
	-rm -f $(BINS)