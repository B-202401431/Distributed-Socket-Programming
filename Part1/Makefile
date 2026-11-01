CC = gcc
CFLAGS = -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror -pthread

all: server client

server: server.c common.h config.h
	$(CC) $(CFLAGS) server.c -o server

client: client.c common.h config.h
	$(CC) $(CFLAGS) client.c -o client

clean:
	rm -f server client

.PHONY: all clean
