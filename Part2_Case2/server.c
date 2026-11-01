#include "config.h"
#include "common.h"
/* One immutable topic entry per directory. Linear lookup is enough for 10 topics. */
typedef struct { char *name; char *path; struct timespec modified; Manifest m; } Topic;
typedef struct Session {
    uint64_t id, hash, index, offset;
    unsigned lane, lanes;
    struct Session *next;
} Session;
typedef struct { int fd; unsigned seed; } Job;
static Topic *topics;
static size_t topic_count, session_count;
static Session *sessions;
static pthread_mutex_t state_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t log_lock=PTHREAD_MUTEX_INITIALIZER;
static double failure_probability;
static uint64_t hash_bytes(uint64_t h,const void *data,size_t n) {
    const unsigned char *p=data;
    for(size_t i=0;i<n;i++) { h^=p[i]; h*=UINT64_C(1099511628211); }
    return h;
}
static int file_cmp(const void *a,const void *b) {
    return strcmp(((const File *)a)->name,((const File *)b)->name);
}
static int load_files(Topic *t) {
    DIR *d=opendir(t->path); if(!d) return -1;
    struct stat directory_stat;
    if(fstat(dirfd(d),&directory_stat)) {closedir(d);return -1;}
    t->modified=directory_stat.st_mtim;
    struct dirent *e; Manifest *m=&t->m;
    while((e=readdir(d))) {
        if(!strcmp(e->d_name,".") || !strcmp(e->d_name,"..")) continue;
        struct stat st;
        if(fstatat(dirfd(d),e->d_name,&st,AT_SYMLINK_NOFOLLOW)) {closedir(d);return -1;}
        if(!S_ISREG(st.st_mode)) continue; /* No symlinks or recursive traversal. */
        if(!safe_name(e->d_name) || m->count>=MAX_FILES) {closedir(d);return -1;}
        File *f=realloc(m->files,(m->count+1)*sizeof *f);
        if(!f) {closedir(d);return -1;} m->files=f;
        m->files[m->count].name=strdup(e->d_name);
        if(!m->files[m->count].name) {closedir(d);return -1;}
        m->files[m->count].size=(uint64_t)st.st_size; m->count++;
    }
    closedir(d);
    if(m->count>1) qsort(m->files,m->count,sizeof(File),file_cmp);
    m->hash=UINT64_C(14695981039346656037);
    m->hash=hash_bytes(m->hash,t->name,strlen(t->name)+1);
    for(size_t i=0;i<m->count;i++) {
        struct stat st; char p[PATH_MAX];
        if(snprintf(p,sizeof p,"%s/%s",t->path,m->files[i].name)>=(int)sizeof p || stat(p,&st)) return -1;
        m->files[i].modified=st.st_mtim;
        m->hash=hash_bytes(m->hash,m->files[i].name,strlen(m->files[i].name)+1);
        m->hash=hash_bytes(m->hash,&m->files[i].size,sizeof(uint64_t));
        m->hash=hash_bytes(m->hash,&st.st_mtim,sizeof st.st_mtim);
        m->total+=m->files[i].size;
    }
    return 0;
}
/* Reject an old checkpoint if the server's startup snapshot has changed.
   This is metadata validation, not a cryptographic content checksum. */
static int same_time(struct timespec a,struct timespec b) {
    return a.tv_sec==b.tv_sec && a.tv_nsec==b.tv_nsec;
}
static int topic_unchanged(Topic *t) {
    DIR *d=opendir(t->path); if(!d) return 0;
    struct stat st;
    if(fstat(dirfd(d),&st) || !same_time(st.st_mtim,t->modified)) {closedir(d);return 0;}
    for(size_t i=0;i<t->m.count;i++) {
        File *f=&t->m.files[i];
        if(fstatat(dirfd(d),f->name,&st,AT_SYMLINK_NOFOLLOW) || !S_ISREG(st.st_mode) ||
           (uint64_t)st.st_size!=f->size || !same_time(st.st_mtim,f->modified)) {
            closedir(d);return 0;
        }
    }
    closedir(d);return 1;
}
static int add_topic(const char *name,const char *path) {
    struct stat st;
    if(!safe_name(name) || lstat(path,&st) || !S_ISDIR(st.st_mode)) return -1;
    for(size_t i=0;i<topic_count;i++) if(!strcmp(topics[i].name,name)) return -1;
    Topic *p=realloc(topics,(topic_count+1)*sizeof *p);
    if(!p) return -1;
    topics=p;Topic *t=&topics[topic_count++];memset(t,0,sizeof *t);
    t->name=strdup(name);t->path=realpath(path,NULL);
    return !t->name || !t->path || load_files(t) ? -1 : 0;
}
static int load_topics(const char *root) {
    char *absolute=realpath(root,NULL); if(!absolute) return -1;
    DIR *d=opendir(absolute); if(!d) {free(absolute);return -1;}
    /* Optional key-style mapping: topic<TAB>relative-directory, one per line.
       The required root-directory CLI works without this configuration file. */
    int config_fd=openat(dirfd(d),"topics.conf",O_RDONLY|O_NOFOLLOW);
    if(config_fd>=0) {
        FILE *config=fdopen(config_fd,"r");char *line=NULL;size_t capacity=0;int result=0;
        if(!config) {close(config_fd);closedir(d);free(absolute);return -1;}
        while(getline(&line,&capacity,config)>=0) {
            line[strcspn(line,"\r\n")]=0;
            if(!*line || *line=='#') continue;
            char *tab=strchr(line,'\t');
            if(!tab || strchr(tab+1,'\t')) {result=-1;break;}
            *tab++=0;char path[PATH_MAX];
            if(!*tab || *tab=='/' || snprintf(path,sizeof path,"%s/%s",absolute,tab)>=(int)sizeof path) {result=-1;break;}
            char *resolved=realpath(path,NULL);size_t prefix=strlen(absolute);
            if(!resolved || strncmp(resolved,absolute,prefix) ||
               (prefix>1 && resolved[prefix]!='/') || add_topic(line,path)) result=-1;
            free(resolved);if(result) break;
        }
        if(ferror(config)) result=-1;
        free(line);fclose(config);closedir(d);free(absolute);return result;
    }
    if(errno!=ENOENT) {closedir(d);free(absolute);return -1;}
    struct dirent *e; int result=0;
    while((e=readdir(d))) {
        if(!strcmp(e->d_name,".") || !strcmp(e->d_name,"..")) continue;
        struct stat st;
        if(fstatat(dirfd(d),e->d_name,&st,AT_SYMLINK_NOFOLLOW)) {result=-1;break;}
        if(!S_ISDIR(st.st_mode)) continue;
        if(!safe_name(e->d_name)) {result=-1;break;}
        char path[PATH_MAX];
        if(snprintf(path,sizeof path,"%s/%s",absolute,e->d_name)>=(int)sizeof path || add_topic(e->d_name,path)) {result=-1;break;}
    }
    closedir(d);free(absolute);return result;
}
static Topic *lookup(const char *name) {
    for(size_t i=0;i<topic_count;i++) if(!strcmp(topics[i].name,name)) return &topics[i];
    return NULL;
}
/* State is retained across disconnections, protected by one short-held mutex.
   Client checkpoint is authoritative: an ACK can be lost after data was saved. */
static Session *get_session(uint64_t id,Manifest *m,unsigned lane,unsigned lanes) {
    pthread_mutex_lock(&state_lock);
    Session *s=sessions;
    while(s && !(s->id==id && s->lane==lane)) s=s->next;
    if(s && (s->hash!=m->hash || s->lanes!=lanes)) s=NULL;
    else if(!s && session_count<MAX_SESSIONS) {
        s=calloc(1,sizeof *s);
        if(s) {s->id=id;s->hash=m->hash;s->lane=lane;s->lanes=lanes;s->next=sessions;sessions=s;session_count++;}
    }
    pthread_mutex_unlock(&state_lock);return s;
}
static void checkpoint(Session *s,uint64_t i,uint64_t off) {
    if(!s) return;
    pthread_mutex_lock(&state_lock); s->index=i;s->offset=off; pthread_mutex_unlock(&state_lock);
}
static void *serve(void *arg) {
    Job job=*(Job *)arg; free(arg); int fd=job.fd;
    wire_sent=0;wire_received=0;
    double begin=now_seconds(); uint64_t payload=0,id=0,idx=0,off=0,hash=0;
    unsigned lane=0,lanes=1; int injected=0,complete=0;
    char line[2048],extra; Topic *t=NULL; Session *session=NULL;
    if(read_line(fd,line,sizeof line) || strncmp(line,"GET ",4) || !safe_name(line+4)) goto end;
    t=lookup(line+4);
    if(!t) {send_line(fd,"ERR unknown_topic\n");goto end;}
    if(!topic_unchanged(t)) {send_line(fd,"ERR dataset_changed_restart_server\n");goto end;}
    Manifest *m=&t->m;
    if(send_line(fd,"OK %zu %" PRIu64 " %" PRIu64 "\n",m->count,m->hash,m->total)) goto end;
    for(size_t i=0;i<m->count;i++) {
        size_t n=strlen(m->files[i].name);
        if(put64(fd,n) || send_all(fd,m->files[i].name,n,NULL) || put64(fd,m->files[i].size)) goto end;
    }
    if(read_line(fd,line,sizeof line) || sscanf(line,"START %" SCNu64 " %u %u %" SCNu64 " %" SCNu64 " %" SCNu64 " %c",&id,&lane,&lanes,&idx,&off,&hash,&extra)!=6) goto end;
    if(hash!=m->hash || lanes<1 || lanes>16 || lane>=lanes || idx>m->count ||
       (CASE_MODE!=3 && (lane!=0 || lanes!=1)) ||
       (idx<m->count && (idx%lanes!=lane || off>m->files[idx].size)) ||
       (idx==m->count && off!=0) || (CASE_MODE<2 && (idx!=0 || off!=0))) {
        send_line(fd,"ERR invalid_checkpoint\n");goto end;
    }
    if(CASE_MODE>0) {
        pthread_mutex_lock(&log_lock);
        fprintf(stderr,"\n[CLIENT START]\n");
        fprintf(stderr,"Session                : %" PRIu64 "\n",id);
        fprintf(stderr,"Lane                   : %u/%u\n",lane,lanes);
        fprintf(stderr,"Topic                  : %s\n",t->name);
        fprintf(stderr,"Requested file index   : %" PRIu64 " (0-based)\n",idx);
        fprintf(stderr,"Requested offset       : %" PRIu64 " bytes\n",off);
        fflush(stderr);
        pthread_mutex_unlock(&log_lock);
    }
    if(CASE_MODE>=2) {
        session=get_session(id,m,lane,lanes);
        if(!session) {send_line(fd,"ERR session_mismatch_or_capacity\n");goto end;}
        checkpoint(session,idx,off);
    }
    if(send_line(fd,"READY\n")) goto end;
    for(size_t i=(size_t)idx;i<m->count;i+=lanes) {
        char path[PATH_MAX];
        if(snprintf(path,sizeof path,"%s/%s",t->path,m->files[i].name)>=(int)sizeof path) goto end;
        int file=open(path,O_RDONLY|O_NOFOLLOW); struct stat st;
        if(file<0) goto end;
        if(fstat(file,&st) || !S_ISREG(st.st_mode) || (uint64_t)st.st_size!=m->files[i].size ||
           !same_time(st.st_mtim,m->files[i].modified) || lseek(file,(off_t)off,SEEK_SET)<0) {close(file);goto end;}
        if(send_line(fd,"FILE %zu %" PRIu64 "\n",i,off)) {close(file);goto end;}
        while(off<m->files[i].size) {
            unsigned char buf[CHUNK];
            size_t want=(size_t)((m->files[i].size-off)<CHUNK ? m->files[i].size-off : CHUNK);
            size_t have=0;
            while(have<want && have<sizeof buf) {
                size_t remaining=want-have;
                if(remaining>sizeof buf-have) remaining=sizeof buf-have;
                ssize_t n=read(file,buf+have,remaining);
                if(n<0 && errno==EINTR) continue;
                if(n<=0 || (size_t)n>want-have) {close(file);goto end;}
                have+=(size_t)n;
            }
            if(put64(fd,want)) {close(file);goto end;}
            /* One independent Bernoulli draw before each <=64 KiB payload.
               On failure, send half the block and disconnect mid-frame. */
            if(CASE_MODE>0 && (double)rand_r(&job.seed)/((double)RAND_MAX+1.0)<failure_probability) {
                size_t cut=want/2;
                pthread_mutex_lock(&log_lock);
                fprintf(stderr,"\n[FAULT INJECTED]\n");
                fprintf(stderr,"Session                : %" PRIu64 "\n",id);
                fprintf(stderr,"Lane                   : %u/%u\n",lane,lanes);
                fprintf(stderr,"Topic                  : %s\n",t->name);
                fprintf(stderr,"File index             : %zu (0-based)\n",i);
                fprintf(stderr,"Last confirmed offset  : %" PRIu64 " bytes\n",off);
                fprintf(stderr,"Disconnect file offset : %" PRIu64 " bytes\n",off+(uint64_t)cut);
                fprintf(stderr,"Block size             : %zu bytes\n",want);
                fflush(stderr);
                pthread_mutex_unlock(&log_lock);
                (void)send_all(fd,buf,cut,&payload); injected=1;close(file);goto end;
            }
            if(send_all(fd,buf,want,&payload)) {close(file);goto end;}
            uint64_t ack;
            if(get64(fd,&ack) || ack!=off+want) {close(file);goto end;}
            off=ack;checkpoint(session,i,off);
        }
        close(file);
        /* Zero terminates a file, including an empty file; client acknowledges. */
        uint64_t ack;
        if(put64(fd,0) || get64(fd,&ack) || ack!=off) goto end;
        size_t next=i+lanes; if(next>m->count) next=m->count;
        checkpoint(session,next,0);off=0;
    }
    if(!topic_unchanged(t)) {send_line(fd,"ERR dataset_changed_restart_server\n");goto end;}
    if(send_line(fd,"DONE\n")) goto end;
    if(read_line(fd,line,sizeof line) || strcmp(line,"BYE")) goto end;
    complete=1;
end:
    shutdown(fd,SHUT_RDWR);close(fd);
    pthread_mutex_lock(&log_lock);
    printf("%" PRIu64 ",%u,%s,%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%.9f,%d,%d\n",id,lane,t?t->name:"-",payload,wire_sent,wire_received,now_seconds()-begin,injected,complete);
    fflush(stdout);pthread_mutex_unlock(&log_lock);return NULL;
}
int main(int argc,char **argv) {
    int minimum=CASE_MODE==0?3:4;
    if(argc<minimum || argc>minimum+1) {fprintf(stderr,"Usage: %s <port> <topics_root_dir>%s%s\n",argv[0],CASE_MODE?" <failure_probability>":"",CASE_MODE?"":" [single|multi]");return 1;}
    int port=port_value(argv[1]);
    if(port<0) {fprintf(stderr,"Invalid port\n");return 1;}
    if(CASE_MODE) {
        char *end;errno=0;failure_probability=strtod(argv[3],&end);
        if(errno || !*argv[3] || *end || !(failure_probability>=0 && failure_probability<=1) || argc!=minimum) {fprintf(stderr,"Failure probability must be in [0,1]\n");return 1;}
    }
    int single=0;
    if(!CASE_MODE && argc==4) {
        if(strcmp(argv[3],"single") && strcmp(argv[3],"multi")) {fprintf(stderr,"Use single or multi\n");return 1;}
        single=!strcmp(argv[3],"single");
    }
    if(load_topics(argv[2])) {perror("load topics");return 1;}
    int listener=socket(AF_INET,SOCK_STREAM,0),one=1;
    if(listener<0) {perror("socket");return 1;}
    setsockopt(listener,SOL_SOCKET,SO_REUSEADDR,&one,sizeof one);
    struct sockaddr_in a={0};a.sin_family=AF_INET;a.sin_addr.s_addr=htonl(INADDR_ANY);a.sin_port=htons((uint16_t)port);
    if(bind(listener,(struct sockaddr *)&a,sizeof a) || listen(listener,128)) {perror("bind/listen");close(listener);return 1;}
    printf("session,lane,topic,payload_sent,app_bytes_sent,app_bytes_received,connection_seconds,injected,complete\n");fflush(stdout);
    fprintf(stderr,"Ready: %zu topics, %s, p=%.9g\n",topic_count,single?"single":"multi",failure_probability);
    unsigned seed=(unsigned)time(NULL)^(unsigned)getpid();
    for(;;) {
        int fd=accept(listener,NULL,NULL);
        if(fd<0) {if(errno==EINTR) continue;perror("accept");break;}
        socket_options(fd);Job *j=malloc(sizeof *j);
        if(!j) {close(fd);continue;}
        j->fd=fd;j->seed=rand_r(&seed);
        if(single) serve(j);
        else {pthread_t th;int rc=pthread_create(&th,NULL,serve,j);if(rc) {fprintf(stderr,"pthread_create: %s\n",strerror(rc));close(fd);free(j);} else pthread_detach(th);}
    }
    close(listener);return 1;
}
