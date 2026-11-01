#ifndef COMMON_H
#define COMMON_H
#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#define CHUNK 65536U
#define MAX_FILES 100000U
#define MAX_SESSIONS 4096U
/* All sizes and offsets on the wire are unsigned decimal or big-endian u64. */
static _Thread_local uint64_t wire_sent, wire_received;
typedef struct { char *name; uint64_t size; struct timespec modified; } File;
typedef struct { File *files; size_t count; uint64_t hash, total; } Manifest;
static inline double now_seconds(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static inline int safe_name(const char *s) {
    return *s && strlen(s) <= NAME_MAX && strcmp(s,".") && strcmp(s,"..") &&
           !strchr(s,'/') && !strchr(s,'\n') && !strchr(s,'\r');
}
static inline int number(const char *s, uint64_t *n) {
    char *end; if (!*s || *s=='-' || *s=='+') return -1;
    errno=0; unsigned long long v=strtoull(s,&end,10);
    if (errno || *end) return -1;
    *n=(uint64_t)v; return 0;
}
static inline int port_value(const char *s) {
    uint64_t p; return number(s,&p) || p<1 || p>65535 ? -1 : (int)p;
}
/* Counters include every byte actually accepted by send / returned by recv. */
static inline int send_all(int fd,const void *buf,size_t n,uint64_t *counter) {
    const char *p=buf;
    while(n) {
        ssize_t k=send(fd,p,n,MSG_NOSIGNAL);
        if(k<0 && errno==EINTR) continue;
        if(k<=0) return -1;
        wire_sent+=(uint64_t)k;
        if(counter) *counter+=(uint64_t)k;
        p+=k; n-=(size_t)k;
    }
    return 0;
}
static inline int recv_all(int fd,void *buf,size_t n,uint64_t *counter) {
    char *p=buf;
    while(n) {
        ssize_t k=recv(fd,p,n,0);
        if(k<0 && errno==EINTR) continue;
        if(k<=0) return -1;
        wire_received+=(uint64_t)k;
        if(counter) *counter+=(uint64_t)k;
        p+=k; n-=(size_t)k;
    }
    return 0;
}
static inline int send_line(int fd,const char *fmt,...) {
    char b[2048]; va_list ap; va_start(ap,fmt);
    int n=vsnprintf(b,sizeof b,fmt,ap); va_end(ap);
    return n<0 || (size_t)n>=sizeof b ? -1 : send_all(fd,b,(size_t)n,NULL);
}
static inline int read_line(int fd,char *b,size_t cap) {
    for(size_t i=0;i+1<cap;i++) {
        if(recv_all(fd,b+i,1,NULL)) return -1;
        if(b[i]=='\n') { b[i]=0; return 0; }
    }
    return -1;
}
static inline int put64(int fd,uint64_t v) {
    unsigned char b[8]; for(int i=7;i>=0;i--) {b[i]=(unsigned char)v;v>>=8;}
    return send_all(fd,b,8,NULL);
}
static inline int get64(int fd,uint64_t *v) {
    unsigned char b[8]; if(recv_all(fd,b,8,NULL)) return -1;
    *v=0; for(int i=0;i<8;i++) *v=(*v<<8)|b[i]; return 0;
}
static inline void socket_options(int fd) {
    /* Slow Wi-Fi and queued single-server clients can exceed 30 seconds.
       Optional environment setting preserves the assignment's exact CLI. */
    uint64_t seconds=300, configured;
    const char *setting=getenv("FT_IO_TIMEOUT");
    if(setting && !number(setting,&configured) && configured>=1 && configured<=3600)
        seconds=configured;
    int one=1; struct timeval t={(time_t)seconds,0};
    setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&one,sizeof one);
    setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&t,sizeof t);
    setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&t,sizeof t);
}
static inline void free_manifest(Manifest *m) {
    for(size_t i=0;i<m->count;i++) free(m->files[i].name);
    free(m->files); memset(m,0,sizeof *m);
}
#endif
