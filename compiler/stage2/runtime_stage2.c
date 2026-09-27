
#ifdef _WIN32
#define _CRT_SECURE_NO_WARNINGS
#define _CRT_RAND_S
#else
#define _POSIX_C_SOURCE 200809L
#endif
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <inttypes.h>
#include <limits.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include <math.h>
#include <setjmp.h>
#include <errno.h>
#include <time.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <direct.h>
#include <wchar.h>
#include <mmsystem.h>
typedef SOCKET SvSocketHandle;
typedef int SvSockLen;
#define SV_BAD_SOCKET INVALID_SOCKET
#else
#include <unistd.h>
#include <dirent.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/socket.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <termios.h>
typedef int SvSocketHandle;
typedef socklen_t SvSockLen;
#define SV_BAD_SOCKET (-1)
#endif

typedef struct SlugValue SlugValue;
typedef struct SlugList SlugList;
typedef struct SlugMap SlugMap;
typedef struct SlugObject SlugObject;
typedef struct SlugCell SlugCell;
typedef struct SlugClosure SlugClosure;
typedef struct SlugErrorValue SlugErrorValue;
typedef struct SlugExcFrame SlugExcFrame;
typedef struct SlugScopeFrame SlugScopeFrame;
typedef struct SvHeap SvHeap;
typedef struct SlugString SlugString;
typedef struct SlugBytes SlugBytes;
typedef struct SlugSocket SlugSocket;
typedef struct SlugFile SlugFile;
typedef struct SlugSurface SlugSurface;
typedef struct SlugWindow SlugWindow;
typedef struct SlugAudio SlugAudio;
typedef struct SlugDevice SlugDevice;
typedef struct { size_t n; SlugValue *values; } SlugResult;
typedef SlugResult (*SlugClosureFn)(SlugClosure*, size_t, SlugValue*);

typedef enum { SV_NULL, SV_INT, SV_UINT, SV_FLOAT, SV_STRING, SV_BYTES, SV_SOCKET, SV_FILE, SV_SURFACE, SV_WINDOW, SV_AUDIO, SV_DEVICE, SV_BOOL, SV_LIST, SV_MAP, SV_OBJECT, SV_CALLABLE, SV_ERROR, SV_DEFAULT } SlugTag;
typedef enum { SH_STRING, SH_BYTES, SH_SOCKET, SH_FILE, SH_SURFACE, SH_WINDOW, SH_AUDIO, SH_DEVICE, SH_LIST, SH_MAP, SH_OBJECT, SH_CELL, SH_CLOSURE, SH_ERROR } SvHeapKind;
struct SvHeap { SvHeapKind kind; bool marked; SvHeap *prev, *next; };
struct SlugValue {
    SlugTag tag;
    union { int64_t i; uint64_t u; double f; char *s; SlugBytes *bytes; SlugSocket *sock; SlugFile *file; SlugSurface *surface; SlugWindow *window; SlugAudio *audio; SlugDevice *device; bool b; SlugList *list; SlugMap *map; SlugObject *obj; SlugClosure *closure; SlugErrorValue *err; } as;
};
struct SlugString { SvHeap heap; size_t byte_len, cp_len; bool ascii; char data[]; };
struct SlugBytes { SvHeap heap; size_t len; unsigned char *data; };
struct SlugSocket { SvHeap heap; SvSocketHandle h; bool closed; };
struct SlugFile { SvHeap heap; FILE *f; bool closed; };
struct SlugSurface { SvHeap heap; int width,height; size_t len; unsigned char *pixels; };
struct SlugWindow { SvHeap heap; bool closed; int width,height;
#ifdef _WIN32
    HWND hwnd;
#endif
};
struct SlugAudio { SvHeap heap; bool closed; uint32_t rate; uint16_t channels;
#ifdef _WIN32
    HWAVEOUT out;
#endif
};
struct SlugDevice { SvHeap heap; bool closed;
#ifdef _WIN32
    HANDLE h;
#else
    int fd;
#endif
};
struct SlugCell { SvHeap heap; bool permanent_root; bool heap_owned; SlugValue value; };
struct SlugClosure { SvHeap heap; SlugClosureFn fn; size_t capture_count; SlugCell **captures; };
struct SlugErrorValue { SvHeap heap; SlugValue kind,message,payload,cause,suppressed; };
struct SlugList { SvHeap heap; bool frozen; size_t len, cap; SlugValue *items; };
struct SlugMap { SvHeap heap; bool frozen; size_t len, cap; SlugValue *keys, *vals; };
struct SlugObject {
    SvHeap heap; int class_id; const char *class_name; bool destroyed;
    size_t len, cap; char **names; SlugValue *values; bool *immutable;
};
struct SlugScopeFrame { SlugScopeFrame *prev; size_t temp_base; size_t len, cap; SlugCell **cells; };
typedef struct SvLocalRootFrame SvLocalRootFrame;
struct SvLocalRootFrame { SvLocalRootFrame *prev; size_t len, cap; SlugValue **slots; };
struct SlugExcFrame { jmp_buf env; SlugExcFrame *prev; SlugScopeFrame *scope_base; SvLocalRootFrame *local_root_base; size_t temp_base; SlugValue error; };

static SvHeap *sv_heap_head=NULL;
static size_t sv_heap_allocated=0,sv_heap_freed=0,sv_heap_peak=0,sv_gc_collections=0;
static SlugScopeFrame *sv_scope_top=NULL;
static SvLocalRootFrame *sv_local_root_top=NULL;
static SlugExcFrame *sv_exc_top=NULL;
static SlugValue **sv_root_slots=NULL; static size_t sv_root_slots_len=0,sv_root_slots_cap=0;
static SlugValue *sv_temp_roots=NULL; static size_t sv_temp_roots_len=0,sv_temp_roots_cap=0;
static bool sv_gc_running=false,sv_runtime_stopped=false;
static bool sv_gc_policy_loaded=false; static size_t sv_gc_interval=65536,sv_gc_safepoints=0;

typedef struct { uint64_t hash; SlugString *str; } SvInternSlot;
static SvInternSlot *sv_literal_intern=NULL; static size_t sv_literal_intern_cap=0,sv_literal_intern_len=0;
static int sv_argc=0; static char **sv_argv=NULL;
static void (*sv_object_destructor)(SlugObject*)=NULL;

static void sv_fail(const char *msg);
static void sv_fail_kind(const char *kind,const char *msg);
static void sv_report_uncaught(SlugValue e);
static bool sv_utf8_valid(const unsigned char *s,size_t n);
static void sv_gc_collect(void);
static void sv_gc_safepoint(void);
static void sv_runtime_shutdown(void);
static void sv_temp_root_pop(size_t mark);
static void *sv_xmalloc(size_t n){ void *p=malloc(n?n:1); if(!p){perror("malloc"); exit(70);} return p; }
static void *sv_xrealloc(void *p,size_t n){ void *q=realloc(p,n?n:1); if(!q){perror("realloc"); exit(70);} return q; }
static char *sv_dup(const char *x){ size_t n=strlen(x); char *p=(char*)sv_xmalloc(n+1); memcpy(p,x,n+1); return p; }
static void *sv_heap_alloc(size_t n,SvHeapKind kind){
    SvHeap *h=(SvHeap*)sv_xmalloc(n);memset(h,0,n);h->kind=kind;h->next=sv_heap_head;if(sv_heap_head)sv_heap_head->prev=h;sv_heap_head=h;sv_heap_allocated++;size_t live=sv_heap_allocated-sv_heap_freed;if(live>sv_heap_peak)sv_heap_peak=live;return h;
}
static void sv_heap_unlink(SvHeap *h){if(h->prev)h->prev->next=h->next;else sv_heap_head=h->next;if(h->next)h->next->prev=h->prev;sv_heap_freed++;}

static SlugValue sv_null(void){ SlugValue v={.tag=SV_NULL}; return v; }
static SlugValue sv_int(int64_t x){ SlugValue v={.tag=SV_INT}; v.as.i=x; return v; }
static SlugValue sv_uint(uint64_t x){ SlugValue v={.tag=SV_UINT}; v.as.u=x; return v; }
static SlugValue sv_float(double x){ SlugValue v={.tag=SV_FLOAT}; v.as.f=x; return v; }
static SlugValue sv_bool(bool x){ SlugValue v={.tag=SV_BOOL}; v.as.b=x; return v; }
static SlugString *sv_string_header(char *s){return s?(SlugString*)((char*)s - offsetof(SlugString,data)):NULL;}
static size_t sv_string_bytes(char *s){SlugString *h=sv_string_header(s);return h?h->byte_len:0;}
static size_t sv_string_cps(char *s){SlugString *h=sv_string_header(s);return h?h->cp_len:0;}
static bool sv_string_ascii(char *s){SlugString *h=sv_string_header(s);return h&&h->ascii;}
static SlugValue sv_string_n(const unsigned char *x,size_t n){if(n&&!sv_utf8_valid(x,n))sv_fail_kind("encoding","invalid UTF-8 string");SlugString *o=(SlugString*)sv_heap_alloc(sizeof(SlugString)+n+1,SH_STRING);o->byte_len=n;o->cp_len=0;o->ascii=true;for(size_t i=0;i<n;i++){unsigned char c=x[i];if(c&0x80)o->ascii=false;if((c&0xC0)!=0x80)o->cp_len++;}if(n)memcpy(o->data,x,n);o->data[n]=0;SlugValue v={.tag=SV_STRING};v.as.s=o->data;return v;}
static SlugValue sv_string(const char *x){return sv_string_n((const unsigned char*)(x?x:""),x?strlen(x):0);}
static uint64_t sv_literal_hash(const unsigned char *x,size_t n){uint64_t h=UINT64_C(1469598103934665603);for(size_t i=0;i<n;i++){h^=(uint64_t)x[i];h*=UINT64_C(1099511628211);}h^=(uint64_t)n;h*=UINT64_C(1099511628211);return h?h:UINT64_C(1);}
static void sv_literal_intern_rehash(size_t cap){SvInternSlot *old=sv_literal_intern;size_t oldcap=sv_literal_intern_cap;sv_literal_intern=(SvInternSlot*)calloc(cap,sizeof(SvInternSlot));if(!sv_literal_intern){perror("calloc");exit(70);}sv_literal_intern_cap=cap;sv_literal_intern_len=0;for(size_t i=0;i<oldcap;i++)if(old[i].str){size_t j=(size_t)old[i].hash&(cap-1);while(sv_literal_intern[j].str)j=(j+1)&(cap-1);sv_literal_intern[j]=old[i];sv_literal_intern_len++;}free(old);}
static SlugValue sv_string_literal_n(const unsigned char *x,size_t n){if(!x)x=(const unsigned char*)"";if(!sv_literal_intern_cap)sv_literal_intern_rehash(256);if((sv_literal_intern_len+1)*10>=sv_literal_intern_cap*7)sv_literal_intern_rehash(sv_literal_intern_cap*2);uint64_t h=sv_literal_hash(x,n);size_t j=(size_t)h&(sv_literal_intern_cap-1);while(sv_literal_intern[j].str){SlugString *q=sv_literal_intern[j].str;if(sv_literal_intern[j].hash==h&&q->byte_len==n&&(!n||memcmp(q->data,x,n)==0)){SlugValue v={.tag=SV_STRING};v.as.s=q->data;return v;}j=(j+1)&(sv_literal_intern_cap-1);}SlugValue v=sv_string_n(x,n);sv_literal_intern[j].hash=h;sv_literal_intern[j].str=sv_string_header(v.as.s);sv_literal_intern_len++;return v;}
static SlugValue sv_string_owned_n(unsigned char *x,size_t n){SlugValue v=sv_string_n(x,n);free(x);return v;}
static SlugValue sv_string_owned(char *x){size_t n=x?strlen(x):0;SlugValue v=sv_string_n((const unsigned char*)(x?x:""),n);free(x);return v;}
static bool sv_string_has_nul(SlugValue v){return v.tag==SV_STRING&&v.as.s&&memchr(v.as.s,0,sv_string_bytes(v.as.s))!=NULL;}
static SlugValue sv_bytes(const unsigned char *data,size_t n){SlugBytes *o=(SlugBytes*)sv_heap_alloc(sizeof(SlugBytes),SH_BYTES);o->len=n;o->data=n?(unsigned char*)sv_xmalloc(n):NULL;if(n)memcpy(o->data,data,n);SlugValue v={.tag=SV_BYTES};v.as.bytes=o;return v;}
static void sv_socket_close_raw(SlugSocket *s){if(!s||s->closed)return;
#ifdef _WIN32
closesocket(s->h);
#else
close(s->h);
#endif
s->closed=true;s->h=SV_BAD_SOCKET;}
static SlugValue sv_socket_value(SvSocketHandle h){SlugSocket *s=(SlugSocket*)sv_heap_alloc(sizeof(SlugSocket),SH_SOCKET);s->h=h;s->closed=false;SlugValue v={.tag=SV_SOCKET};v.as.sock=s;return v;}
static void sv_file_close_raw(SlugFile *f){if(!f||f->closed)return;if(f->f)fclose(f->f);f->f=NULL;f->closed=true;}
static SlugValue sv_file_value(FILE *fp){SlugFile *f=(SlugFile*)sv_heap_alloc(sizeof(SlugFile),SH_FILE);f->f=fp;f->closed=false;SlugValue v={.tag=SV_FILE};v.as.file=f;return v;}
static SlugValue sv_surface_value(SlugSurface *x){SlugValue v={.tag=SV_SURFACE};v.as.surface=x;return v;}
static void sv_window_close_raw(SlugWindow *w){if(!w||w->closed)return;
#ifdef _WIN32
if(w->hwnd){DestroyWindow(w->hwnd);w->hwnd=NULL;}
#endif
w->closed=true;}
static SlugValue sv_window_value(SlugWindow *x){SlugValue v={.tag=SV_WINDOW};v.as.window=x;return v;}
static void sv_audio_close_raw(SlugAudio *a){if(!a||a->closed)return;
#ifdef _WIN32
if(a->out){waveOutReset(a->out);waveOutClose(a->out);a->out=NULL;}
#endif
a->closed=true;}
static SlugValue sv_audio_value(SlugAudio *x){SlugValue v={.tag=SV_AUDIO};v.as.audio=x;return v;}
static void sv_device_close_raw(SlugDevice *d){if(!d||d->closed)return;
#ifdef _WIN32
if(d->h&&d->h!=INVALID_HANDLE_VALUE)CloseHandle(d->h);d->h=INVALID_HANDLE_VALUE;
#else
if(d->fd>=0)close(d->fd);d->fd=-1;
#endif
d->closed=true;}
static SlugValue sv_device_value(SlugDevice *x){SlugValue v={.tag=SV_DEVICE};v.as.device=x;return v;}
static SlugValue sv_list_value(SlugList *x){ SlugValue v={.tag=SV_LIST}; v.as.list=x; return v; }
static SlugValue sv_map_value(SlugMap *x){ SlugValue v={.tag=SV_MAP}; v.as.map=x; return v; }
static SlugValue sv_object_value(SlugObject *x){ SlugValue v={.tag=SV_OBJECT}; v.as.obj=x; return v; }
static SlugValue sv_callable_value(SlugClosure *x){ SlugValue v={.tag=SV_CALLABLE}; v.as.closure=x; return v; }
static SlugValue sv_error_value(SlugErrorValue *x){ SlugValue v={.tag=SV_ERROR}; v.as.err=x; return v; }
static SlugValue sv_default(void){ SlugValue v={.tag=SV_DEFAULT}; return v; }

static void sv_scope_enter(SlugScopeFrame *f){f->prev=sv_scope_top;f->temp_base=sv_temp_roots_len;f->len=0;f->cap=0;f->cells=NULL;sv_scope_top=f;}
static void sv_scope_track(SlugCell *c){if(!sv_scope_top){c->permanent_root=true;return;}SlugScopeFrame *f=sv_scope_top;if(f->len==f->cap){f->cap=f->cap?f->cap*2:4;f->cells=(SlugCell**)sv_xrealloc(f->cells,sizeof(SlugCell*)*f->cap);}f->cells[f->len++]=c;}
static void sv_scope_leave(SlugScopeFrame *f){if(sv_scope_top!=f)sv_fail("scope stack corruption");sv_scope_top=f->prev;sv_temp_root_pop(f->temp_base);free(f->cells);f->cells=NULL;f->len=f->cap=0;}
static void sv_scope_unwind_to(SlugScopeFrame *base){while(sv_scope_top&&sv_scope_top!=base)sv_scope_leave(sv_scope_top);if(base&&!sv_scope_top)sv_fail("scope unwind target missing");}
static void sv_scope_unwind_through(SlugScopeFrame *target){while(sv_scope_top){SlugScopeFrame *f=sv_scope_top;sv_scope_leave(f);if(f==target)return;}sv_fail("scope unwind target missing");}
static SlugCell *sv_cell_new(void){ SlugCell *c=(SlugCell*)sv_heap_alloc(sizeof(SlugCell),SH_CELL);c->permanent_root=false;c->heap_owned=true;c->value=sv_null();sv_scope_track(c);return c; }
static void sv_stack_cell_init(SlugCell *c){memset(c,0,sizeof(*c));c->heap.kind=SH_CELL;c->permanent_root=false;c->heap_owned=false;c->value=sv_null();sv_scope_track(c);}
static SlugCell *sv_cell_from(SlugValue v){SlugCell *c=sv_cell_new();c->value=v;return c;}
static SlugClosure *sv_closure_new(SlugClosureFn fn,size_t n,SlugCell **captures){
    SlugClosure *c=(SlugClosure*)sv_heap_alloc(sizeof(SlugClosure),SH_CLOSURE);c->fn=fn;c->capture_count=n;
    c->captures=n?(SlugCell**)sv_xmalloc(sizeof(SlugCell*)*n):NULL;if(n)memcpy(c->captures,captures,sizeof(SlugCell*)*n);return c;
}
static SlugResult sv_invoke(SlugValue callable,size_t argc,SlugValue *argv){
    if(callable.tag!=SV_CALLABLE||!callable.as.closure||!callable.as.closure->fn)sv_fail("callable value required");
    return callable.as.closure->fn(callable.as.closure,argc,argv);
}
static SlugValue sv_error_empty_suppressed(void){
    SlugList *l=(SlugList*)sv_heap_alloc(sizeof(SlugList),SH_LIST);l->frozen=true;l->len=0;l->cap=0;l->items=NULL;return sv_list_value(l);
}
static SlugValue sv_error_new(const char *kind,const char *message,SlugValue payload,SlugValue cause,SlugValue suppressed){
    if(cause.tag!=SV_NULL&&cause.tag!=SV_ERROR)sv_fail("internal error cause must be ER or nn");
    if(suppressed.tag==SV_NULL)suppressed=sv_error_empty_suppressed();
    if(suppressed.tag!=SV_LIST||!suppressed.as.list||!suppressed.as.list->frozen)sv_fail("internal suppressed errors must be a frozen list");
    for(size_t i=0;i<suppressed.as.list->len;i++)if(suppressed.as.list->items[i].tag!=SV_ERROR)sv_fail("internal suppressed entry must be ER");
    SlugErrorValue *e=(SlugErrorValue*)sv_heap_alloc(sizeof(SlugErrorValue),SH_ERROR);
    e->kind=sv_string(kind?kind:"state");e->message=sv_string(message?message:"");e->payload=payload;e->cause=cause;e->suppressed=suppressed;return sv_error_value(e);
}
static SlugValue sv_wrap_error(SlugValue payload){if(payload.tag==SV_ERROR)return payload;return sv_error_new("user","user error",payload,sv_null(),sv_null());}
static SlugValue sv_error_supersede(SlugValue newer,SlugValue prior){
    newer=sv_wrap_error(newer);prior=sv_wrap_error(prior);SlugErrorValue *e=newer.as.err;
    if(e->cause.tag==SV_NULL)return sv_error_new(e->kind.as.s?e->kind.as.s:"state",e->message.as.s?e->message.as.s:"",e->payload,prior,e->suppressed);
    size_t n=e->suppressed.as.list?e->suppressed.as.list->len:0;
    SlugList *l=(SlugList*)sv_heap_alloc(sizeof(SlugList),SH_LIST);l->frozen=true;l->len=n+1;l->cap=n+1;l->items=(SlugValue*)sv_xmalloc(sizeof(SlugValue)*(n+1));
    if(n)memcpy(l->items,e->suppressed.as.list->items,sizeof(SlugValue)*n);l->items[n]=prior;
    return sv_error_new(e->kind.as.s?e->kind.as.s:"state",e->message.as.s?e->message.as.s:"",e->payload,e->cause,sv_list_value(l));
}
static size_t sv_temp_root_push(SlugValue v){size_t mark=sv_temp_roots_len;if(sv_temp_roots_len==sv_temp_roots_cap){sv_temp_roots_cap=sv_temp_roots_cap?sv_temp_roots_cap*2:8;sv_temp_roots=(SlugValue*)sv_xrealloc(sv_temp_roots,sizeof(SlugValue)*sv_temp_roots_cap);}sv_temp_roots[sv_temp_roots_len++]=v;return mark;}
static void sv_temp_root_pop(size_t mark){if(mark>sv_temp_roots_len)sv_fail("temporary root stack corruption");sv_temp_roots_len=mark;}
static void sv_root_slot(SlugValue *slot){if(sv_root_slots_len==sv_root_slots_cap){sv_root_slots_cap=sv_root_slots_cap?sv_root_slots_cap*2:8;sv_root_slots=(SlugValue**)sv_xrealloc(sv_root_slots,sizeof(SlugValue*)*sv_root_slots_cap);}sv_root_slots[sv_root_slots_len++]=slot;}
static void sv_local_root_enter(SvLocalRootFrame *f){f->prev=sv_local_root_top;f->len=0;f->cap=0;f->slots=NULL;sv_local_root_top=f;}
static void sv_local_root_add(SvLocalRootFrame *f,SlugValue *slot){if(!f||!slot)sv_fail("invalid local root");for(size_t i=0;i<f->len;i++)if(f->slots[i]==slot)return;if(f->len==f->cap){f->cap=f->cap?f->cap*2:16;f->slots=(SlugValue**)sv_xrealloc(f->slots,sizeof(SlugValue*)*f->cap);}f->slots[f->len++]=slot;}
static void sv_local_root_leave(SvLocalRootFrame *f){if(sv_local_root_top!=f)sv_fail("local root frame corruption");sv_local_root_top=f->prev;free(f->slots);f->slots=NULL;f->len=f->cap=0;}
static void sv_exc_push(SlugExcFrame *f){f->prev=sv_exc_top;f->scope_base=sv_scope_top;f->local_root_base=sv_local_root_top;f->temp_base=sv_temp_roots_len;f->error=sv_null();sv_exc_top=f;}
static void sv_exc_pop(SlugExcFrame *f){if(sv_exc_top!=f)sv_fail("exception frame corruption");sv_exc_top=f->prev;}
static void sv_raise(SlugValue value){SlugValue e=sv_wrap_error(value);if(!sv_exc_top){sv_report_uncaught(e);exit(66);}SlugExcFrame *target=sv_exc_top;target->error=e;sv_scope_unwind_to(target->scope_base);while(sv_local_root_top!=target->local_root_base){SvLocalRootFrame *f=sv_local_root_top;if(!f)sv_fail("local root unwind corruption");sv_local_root_top=f->prev;free(f->slots);f->slots=NULL;f->len=f->cap=0;}sv_temp_root_pop(target->temp_base);longjmp(target->env,1);}
static SlugResult sv_result0(void){ SlugResult r={0,NULL}; return r; }
static SlugResult sv_result_from(const SlugValue *items,size_t n){
    SlugResult r={n,NULL};if(!n)return r;r.values=(SlugValue*)sv_xmalloc(sizeof(SlugValue)*n);memcpy(r.values,items,sizeof(SlugValue)*n);return r;
}
static void sv_result_dispose(SlugResult r){free(r.values);}
static void sv_result_require_arity(SlugResult r,size_t targets){if(r.n!=targets)sv_fail_kind("arity","function result arity does not match assignment targets");}
static SlugValue sv_result_first(SlugResult r){if(r.n<1){sv_result_dispose(r);sv_fail("function returned no value where one was required");}SlugValue v=r.values[0];sv_result_dispose(r);return v;}
static SlugValue sv_result_pick(SlugResult r,size_t i,size_t targets){
    if(r.n==0)sv_fail("function returned no values");if(r.n==1)return r.values[0];if(r.n<targets)sv_fail("function returned fewer values than assignment targets");return r.values[i];
}
static void sv_result_discard(SlugResult r){sv_result_dispose(r);}
static size_t sv_result_root(SlugResult r){size_t mark=sv_temp_roots_len;for(size_t i=0;i<r.n;i++)sv_temp_root_push(r.values[i]);return mark;}

static size_t sv_utf8_next(const char *s,size_t n,size_t i){
    if(i>=n) return n; unsigned char c=(unsigned char)s[i];
    size_t k=(c<0x80)?1:((c&0xE0)==0xC0?2:((c&0xF0)==0xE0?3:((c&0xF8)==0xF0?4:1)));
    return i+k>n?n:i+k;
}
static size_t sv_utf8_len(const char *s){ size_t n=strlen(s),i=0,c=0; while(i<n){i=sv_utf8_next(s,n,i);c++;} return c; }
static size_t sv_utf8_offset(const char *s,size_t cp){ size_t n=strlen(s),i=0,c=0; while(i<n && c<cp){i=sv_utf8_next(s,n,i);c++;} return i; }
static size_t sv_utf8_offset_n(const char *s,size_t n,size_t cp){size_t i=0,c=0;while(i<n&&c<cp){i=sv_utf8_next(s,n,i);c++;}return i;}

static double sv_num(SlugValue v){
    if(v.tag==SV_INT) return (double)v.as.i;
    if(v.tag==SV_UINT) return (double)v.as.u;
    if(v.tag==SV_FLOAT) return v.as.f;
    if(v.tag==SV_BOOL) return v.as.b?1.0:0.0;
    sv_fail("numeric value required"); return 0;
}
static int64_t sv_i64_numeric(SlugValue v){
    if(v.tag==SV_INT)return v.as.i;
    if(v.tag==SV_UINT){if(v.as.u>(uint64_t)INT64_MAX)sv_fail("integer conversion out of range");return (int64_t)v.as.u;}
    if(v.tag==SV_BOOL)return v.as.b?1:0;
    if(v.tag==SV_FLOAT){
        double x=v.as.f;
        if(!isfinite(x)||x < -9223372036854775808.0 || x >= 9223372036854775808.0)sv_fail("integer conversion out of range");
        return (int64_t)x;
    }
    sv_fail("numeric value required");return 0;
}
static uint64_t sv_u64_numeric(SlugValue v){
    if(v.tag==SV_UINT)return v.as.u;
    if(v.tag==SV_INT){if(v.as.i<0)sv_fail("negative value cast to unsigned");return (uint64_t)v.as.i;}
    if(v.tag==SV_BOOL)return v.as.b?1:0;
    if(v.tag==SV_FLOAT){double x=v.as.f;if(!isfinite(x)||x<0.0||x>=18446744073709551616.0)sv_fail("unsigned integer conversion out of range");return (uint64_t)x;}
    sv_fail("numeric value required");return 0;
}
static int64_t sv_int_num(SlugValue v){ return sv_i64_numeric(v); }

typedef struct { bool neg; uint64_t mag; bool prefer_unsigned; } SvWideInt;
static SvWideInt sv_wint(SlugValue v){
    if(v.tag==SV_UINT)return (SvWideInt){false,v.as.u,true};
    if(v.tag==SV_INT){if(v.as.i<0){uint64_t m=(uint64_t)(-(v.as.i+1))+1;return (SvWideInt){true,m,false};}return (SvWideInt){false,(uint64_t)v.as.i,false};}
    if(v.tag==SV_BOOL)return (SvWideInt){false,v.as.b?1u:0u,false};
    sv_fail("integer value required");return (SvWideInt){false,0,false};
}
static SlugValue sv_wint_value(bool neg,uint64_t mag,bool prefer_unsigned){
    if(mag==0)return prefer_unsigned?sv_uint(0):sv_int(0);
    if(neg){
        const uint64_t lim=UINT64_C(9223372036854775808);if(mag>lim)sv_fail("integer overflow");
        if(mag==lim)return sv_int(INT64_MIN);return sv_int(-(int64_t)mag);
    }
    if(prefer_unsigned)return sv_uint(mag);
    if(mag>(uint64_t)INT64_MAX)sv_fail("integer overflow");
    return sv_int((int64_t)mag);
}
static SlugValue sv_wadd(SvWideInt a,SvWideInt b){
    bool pref=a.prefer_unsigned||b.prefer_unsigned;
    if(a.neg==b.neg){if(UINT64_MAX-a.mag<b.mag)sv_fail("integer overflow");return sv_wint_value(a.neg,a.mag+b.mag,pref&&!a.neg);}
    if(a.mag>=b.mag)return sv_wint_value(a.neg,a.mag-b.mag,pref&&!a.neg);
    return sv_wint_value(b.neg,b.mag-a.mag,pref&&!b.neg);
}
static SlugValue sv_wsub(SvWideInt a,SvWideInt b){b.neg=!b.neg;return sv_wadd(a,b);}
static SlugValue sv_wmul(SvWideInt a,SvWideInt b){
    if(a.mag&&b.mag>UINT64_MAX/a.mag)sv_fail("integer overflow");
    bool neg=a.neg!=b.neg;return sv_wint_value(neg,a.mag*b.mag,(a.prefer_unsigned||b.prefer_unsigned)&&!neg);
}
static bool sv_truthy(SlugValue v){
    switch(v.tag){
        case SV_NULL: return false; case SV_BOOL: return v.as.b; case SV_INT: return v.as.i!=0; case SV_UINT: return v.as.u!=0;
        case SV_FLOAT: return v.as.f!=0.0; case SV_STRING: return v.as.s && sv_string_bytes(v.as.s)!=0; case SV_BYTES: return v.as.bytes && v.as.bytes->len!=0; case SV_SOCKET: return v.as.sock&&!v.as.sock->closed; case SV_FILE: return v.as.file&&!v.as.file->closed; case SV_SURFACE:return v.as.surface!=NULL; case SV_WINDOW:return v.as.window&&!v.as.window->closed; case SV_AUDIO:return v.as.audio&&!v.as.audio->closed; case SV_DEVICE:return v.as.device&&!v.as.device->closed;
        case SV_LIST: return v.as.list && v.as.list->len!=0; case SV_MAP: return v.as.map && v.as.map->len!=0;
        case SV_OBJECT: return v.as.obj!=NULL;
        case SV_CALLABLE: return v.as.closure!=NULL;
        case SV_ERROR: return true;
        case SV_DEFAULT: sv_fail("default placeholder escaped call argument context"); return false;
    } return false;
}


static bool sv_numeric_tag(SlugTag t){return t==SV_INT||t==SV_UINT||t==SV_FLOAT;}
static int sv_cmp_int_float(SlugValue iv,double f){
    if(!isfinite(f))sv_fail("non-finite float escaped runtime");
    if(iv.tag==SV_INT){
        if(f < -9223372036854775808.0)return 1;
        if(f >= 9223372036854775808.0)return -1;
        int64_t fi=(int64_t)f;if(iv.as.i<fi)return -1;if(iv.as.i>fi)return 1;
        double back=(double)fi;return (back>f)-(back<f);
    }
    if(f<0.0)return 1;
    if(f>=18446744073709551616.0)return -1;
    uint64_t fu=(uint64_t)f;if(iv.as.u<fu)return -1;if(iv.as.u>fu)return 1;
    double back=(double)fu;return (back>f)-(back<f);
}
static int sv_numeric_compare(SlugValue a,SlugValue b){
    if(a.tag==SV_INT&&b.tag==SV_INT)return (a.as.i>b.as.i)-(a.as.i<b.as.i);
    if(a.tag==SV_UINT&&b.tag==SV_UINT)return (a.as.u>b.as.u)-(a.as.u<b.as.u);
    if(a.tag==SV_INT&&b.tag==SV_UINT){if(a.as.i<0)return -1;uint64_t x=(uint64_t)a.as.i;return (x>b.as.u)-(x<b.as.u);}
    if(a.tag==SV_UINT&&b.tag==SV_INT){if(b.as.i<0)return 1;uint64_t y=(uint64_t)b.as.i;return (a.as.u>y)-(a.as.u<y);}
    if(a.tag==SV_FLOAT&&b.tag==SV_FLOAT)return (a.as.f>b.as.f)-(a.as.f<b.as.f);
    if(a.tag==SV_FLOAT)return -sv_cmp_int_float(b,a.as.f);
    if(b.tag==SV_FLOAT)return sv_cmp_int_float(a,b.as.f);
    sv_fail("numeric value required");return 0;
}

typedef struct { SlugTag tag; const void *a; const void *b; } SvEqPair;
typedef struct { SvEqPair *pairs; size_t len, cap; } SvEqCtx;
static bool sv_equal_ctx(SlugValue a, SlugValue b, SvEqCtx *ctx);
static bool sv_eq_seen_or_add(SvEqCtx *ctx,SlugTag tag,const void *a,const void *b){
    if(a==b)return true;
    for(size_t i=0;i<ctx->len;i++)if(ctx->pairs[i].tag==tag&&ctx->pairs[i].a==a&&ctx->pairs[i].b==b)return true;
    if(ctx->len==ctx->cap){ctx->cap=ctx->cap?ctx->cap*2:16;ctx->pairs=(SvEqPair*)sv_xrealloc(ctx->pairs,sizeof(SvEqPair)*ctx->cap);}
    ctx->pairs[ctx->len++]=(SvEqPair){tag,a,b};
    return false;
}
static bool sv_equal(SlugValue a, SlugValue b){SvEqCtx ctx={0};bool r=sv_equal_ctx(a,b,&ctx);free(ctx.pairs);return r;}
static int sv_map_find_ctx(SlugMap *m,SlugValue key,SvEqCtx *ctx){
    for(size_t i=0;i<m->len;i++)if(sv_equal_ctx(m->keys[i],key,ctx))return (int)i;
    return -1;
}
static int sv_map_find(SlugMap *m, SlugValue key){SvEqCtx ctx={0};int r=sv_map_find_ctx(m,key,&ctx);free(ctx.pairs);return r;}
static bool sv_equal_ctx(SlugValue a, SlugValue b, SvEqCtx *ctx){
    if(a.tag==SV_INT&&b.tag==SV_INT)return a.as.i==b.as.i;
    if(a.tag==SV_UINT&&b.tag==SV_UINT)return a.as.u==b.as.u;
    if(a.tag==SV_INT&&b.tag==SV_UINT)return a.as.i>=0&&(uint64_t)a.as.i==b.as.u;
    if(a.tag==SV_UINT&&b.tag==SV_INT)return b.as.i>=0&&a.as.u==(uint64_t)b.as.i;
    if(sv_numeric_tag(a.tag)&&sv_numeric_tag(b.tag))return sv_numeric_compare(a,b)==0;
    if(a.tag!=b.tag) return false;
    switch(a.tag){
        case SV_NULL: return true; case SV_BOOL: return a.as.b==b.as.b; case SV_INT: return a.as.i==b.as.i; case SV_UINT: return a.as.u==b.as.u;
        case SV_FLOAT: return a.as.f==b.as.f; case SV_STRING:{size_t an=sv_string_bytes(a.as.s),bn=sv_string_bytes(b.as.s);return an==bn&&(!an||memcmp(a.as.s,b.as.s,an)==0);}
        case SV_BYTES: return a.as.bytes==b.as.bytes || (a.as.bytes&&b.as.bytes&&a.as.bytes->len==b.as.bytes->len&&(!a.as.bytes->len||memcmp(a.as.bytes->data,b.as.bytes->data,a.as.bytes->len)==0));
        case SV_SOCKET:return a.as.sock==b.as.sock;
        case SV_FILE:return a.as.file==b.as.file;
        case SV_SURFACE:return a.as.surface==b.as.surface;
        case SV_WINDOW:return a.as.window==b.as.window;
        case SV_AUDIO:return a.as.audio==b.as.audio;
        case SV_DEVICE:return a.as.device==b.as.device;
        case SV_LIST:
            if(a.as.list==b.as.list)return true;
            if(!a.as.list||!b.as.list||a.as.list->len!=b.as.list->len)return false;
            if(sv_eq_seen_or_add(ctx,SV_LIST,a.as.list,b.as.list))return true;
            for(size_t i=0;i<a.as.list->len;i++)if(!sv_equal_ctx(a.as.list->items[i],b.as.list->items[i],ctx))return false;
            return true;
        case SV_MAP:
            if(a.as.map==b.as.map)return true;
            if(!a.as.map||!b.as.map||a.as.map->len!=b.as.map->len)return false;
            if(sv_eq_seen_or_add(ctx,SV_MAP,a.as.map,b.as.map))return true;
            for(size_t i=0;i<a.as.map->len;i++){
                int j=sv_map_find_ctx(b.as.map,a.as.map->keys[i],ctx);if(j<0)return false;
                if(!sv_equal_ctx(a.as.map->vals[i],b.as.map->vals[j],ctx))return false;
            }
            return true;
        case SV_OBJECT:
            if(a.as.obj==b.as.obj)return true;
            if(!a.as.obj||!b.as.obj||a.as.obj->class_id!=b.as.obj->class_id||a.as.obj->len!=b.as.obj->len)return false;
            if(sv_eq_seen_or_add(ctx,SV_OBJECT,a.as.obj,b.as.obj))return true;
            for(size_t i=0;i<a.as.obj->len;i++){
                int found=-1;
                for(size_t j=0;j<b.as.obj->len;j++)if(strcmp(a.as.obj->names[i],b.as.obj->names[j])==0){found=(int)j;break;}
                if(found<0||!sv_equal_ctx(a.as.obj->values[i],b.as.obj->values[found],ctx))return false;
            }
            return true;
        case SV_CALLABLE:return a.as.closure==b.as.closure;
        case SV_ERROR:
            if(a.as.err==b.as.err)return true;
            if(!a.as.err||!b.as.err)return false;
            if(sv_eq_seen_or_add(ctx,SV_ERROR,a.as.err,b.as.err))return true;
            return sv_equal_ctx(a.as.err->kind,b.as.err->kind,ctx)&&sv_equal_ctx(a.as.err->message,b.as.err->message,ctx)&&sv_equal_ctx(a.as.err->payload,b.as.err->payload,ctx)&&sv_equal_ctx(a.as.err->cause,b.as.err->cause,ctx)&&sv_equal_ctx(a.as.err->suppressed,b.as.err->suppressed,ctx);
        case SV_DEFAULT:return true;
    }
    return false;
}
static bool sv_identical(SlugValue a, SlugValue b){
    if(a.tag!=b.tag) return false;
    if(a.tag==SV_STRING) return a.as.s==b.as.s;
    if(a.tag==SV_BYTES) return a.as.bytes==b.as.bytes;
    if(a.tag==SV_SOCKET) return a.as.sock==b.as.sock;
    if(a.tag==SV_FILE) return a.as.file==b.as.file;
    if(a.tag==SV_SURFACE) return a.as.surface==b.as.surface;
    if(a.tag==SV_WINDOW) return a.as.window==b.as.window;
    if(a.tag==SV_AUDIO) return a.as.audio==b.as.audio;
    if(a.tag==SV_DEVICE) return a.as.device==b.as.device;
    if(a.tag==SV_LIST) return a.as.list==b.as.list;
    if(a.tag==SV_MAP) return a.as.map==b.as.map;
    if(a.tag==SV_OBJECT) return a.as.obj==b.as.obj;
    if(a.tag==SV_CALLABLE) return a.as.closure==b.as.closure;
    if(a.tag==SV_ERROR) return a.as.err==b.as.err;
    return sv_equal(a,b);
}
static int sv_compare(SlugValue a, SlugValue b){
    if(sv_numeric_tag(a.tag)&&sv_numeric_tag(b.tag))return sv_numeric_compare(a,b);
    if(a.tag==SV_STRING && b.tag==SV_STRING){size_t an=sv_string_bytes(a.as.s),bn=sv_string_bytes(b.as.s),n=an<bn?an:bn;int c=n?memcmp(a.as.s,b.as.s,n):0;if(c)return (c>0)-(c<0);return (an>bn)-(an<bn);}
    if(a.tag==SV_BYTES && b.tag==SV_BYTES){size_t n=a.as.bytes->len<b.as.bytes->len?a.as.bytes->len:b.as.bytes->len;int c=n?memcmp(a.as.bytes->data,b.as.bytes->data,n):0;if(c)return (c>0)-(c<0);return (a.as.bytes->len>b.as.bytes->len)-(a.as.bytes->len<b.as.bytes->len);}
    sv_fail("incomparable values"); return 0;
}

static SlugList *sv_list_new_raw(bool frozen,size_t n){
    SlugList *l=(SlugList*)sv_heap_alloc(sizeof(SlugList),SH_LIST); l->frozen=frozen; l->len=n; l->cap=n;
    l->items=n?(SlugValue*)sv_xmalloc(sizeof(SlugValue)*n):NULL; return l;
}
static SlugValue sv_list_empty(bool frozen){ return sv_list_value(sv_list_new_raw(frozen,0)); }
static SlugValue sv_list_from(SlugValue *items,size_t n,bool frozen){
    SlugList *l=sv_list_new_raw(frozen,n); if(n) memcpy(l->items,items,sizeof(SlugValue)*n); return sv_list_value(l);
}
static SlugValue sv_list_from_args(SlugValue *items,size_t n){ return n?sv_list_from(items,n,false):sv_list_empty(false); }
static void sv_list_append(SlugList *l,SlugValue v){if(l->frozen)sv_fail("cannot mutate frozen list");if(l->len==l->cap){size_t cap=l->cap?l->cap*2:4;l->items=(SlugValue*)sv_xrealloc(l->items,sizeof(SlugValue)*cap);l->cap=cap;}l->items[l->len++]=v;}
static int64_t sv_norm_index(int64_t i,int64_t n);
static SlugList *sv_require_mutable_list_value(SlugValue v,const char *op){if(v.tag!=SV_LIST||!v.as.list)sv_fail_kind("type",op);if(v.as.list->frozen)sv_fail_kind("immutable","cannot mutate frozen list");return v.as.list;}
static size_t sv_list_api_index_position(SlugValue iv,size_t n,bool allow_end,const char *message){
    if(iv.tag==SV_UINT){if(iv.as.u>(uint64_t)SIZE_MAX||(allow_end?(size_t)iv.as.u>n:(size_t)iv.as.u>=n))sv_fail_kind("index",message);return(size_t)iv.as.u;}
    if(iv.tag!=SV_INT)sv_fail_kind("type",allow_end?"list insertion index must be an integer":"list pop index must be an integer");
    if(iv.as.i>=0){uint64_t u=(uint64_t)iv.as.i;if(u>(uint64_t)SIZE_MAX||(allow_end?(size_t)u>n:(size_t)u>=n))sv_fail_kind("index",message);return(size_t)u;}
    uint64_t mag=(uint64_t)(-(iv.as.i+1))+1;if(mag>(uint64_t)n)sv_fail_kind("index",message);return n-(size_t)mag;
}
static SlugValue sv_list_api_append(SlugValue lv,SlugValue value){SlugList *l=sv_require_mutable_list_value(lv,"LI.ap requires list");sv_list_append(l,value);return lv;}
static SlugValue sv_list_api_insert(SlugValue lv,SlugValue index,SlugValue value){SlugList *l=sv_require_mutable_list_value(lv,"LI.ip requires list");size_t i=sv_list_api_index_position(index,l->len,true,"list insertion index out of range");if(l->len==l->cap){if(l->cap>SIZE_MAX/2)sv_fail_kind("resource","list capacity overflow");size_t cap=l->cap?l->cap*2:4;if(cap>SIZE_MAX/sizeof(SlugValue))sv_fail_kind("resource","list capacity overflow");l->items=(SlugValue*)sv_xrealloc(l->items,sizeof(SlugValue)*cap);l->cap=cap;}if(i<l->len){size_t count=l->len-i;if(count>SIZE_MAX/sizeof(SlugValue))sv_fail_kind("resource","list insert move overflow");memmove(l->items+i+1,l->items+i,sizeof(SlugValue)*count);}l->items[i]=value;l->len++;return lv;}
static SlugValue sv_list_api_remove(SlugValue lv,SlugValue value){SlugList *l=sv_require_mutable_list_value(lv,"LI.rm requires list");for(size_t i=0;i<l->len;i++)if(sv_equal(l->items[i],value)){if(i+1<l->len){size_t count=l->len-i-1;if(count>SIZE_MAX/sizeof(SlugValue))sv_fail_kind("resource","list remove move overflow");memmove(l->items+i,l->items+i+1,sizeof(SlugValue)*count);}l->len--;if(l->items)l->items[l->len]=sv_null();return sv_bool(true);}return sv_bool(false);}
static SlugValue sv_list_api_pop(SlugValue lv,bool has_index,SlugValue index){SlugList *l=sv_require_mutable_list_value(lv,"LI.pp requires list");if(!l->len)sv_fail_kind("index","cannot pop from empty list");size_t i=has_index?sv_list_api_index_position(index,l->len,false,"list pop index out of range"):l->len-1;SlugValue out=l->items[i];if(i+1<l->len){size_t count=l->len-i-1;if(count>SIZE_MAX/sizeof(SlugValue))sv_fail_kind("resource","list pop move overflow");memmove(l->items+i,l->items+i+1,sizeof(SlugValue)*count);}l->len--;l->items[l->len]=sv_null();return out;}
static SlugMap *sv_map_new_raw(bool frozen,size_t n){
    SlugMap *m=(SlugMap*)sv_heap_alloc(sizeof(SlugMap),SH_MAP); m->frozen=frozen; m->len=0; m->cap=n;
    m->keys=n?(SlugValue*)sv_xmalloc(sizeof(SlugValue)*n):NULL; m->vals=n?(SlugValue*)sv_xmalloc(sizeof(SlugValue)*n):NULL; return m;
}
static void sv_map_reserve(SlugMap *m,size_t need){
    if(need<=m->cap) return; size_t cap=m->cap?m->cap*2:4; while(cap<need) cap*=2;
    m->keys=(SlugValue*)sv_xrealloc(m->keys,sizeof(SlugValue)*cap); m->vals=(SlugValue*)sv_xrealloc(m->vals,sizeof(SlugValue)*cap); m->cap=cap;
}
static void sv_map_put_raw(SlugMap *m,SlugValue k,SlugValue v){
    int i=sv_map_find(m,k); if(i>=0){m->vals[i]=v;return;} sv_map_reserve(m,m->len+1); m->keys[m->len]=k; m->vals[m->len]=v; m->len++;
}
static SlugValue sv_map_empty(bool frozen){ return sv_map_value(sv_map_new_raw(frozen,0)); }
static SlugValue sv_map_from(SlugValue *flat,size_t pairs,bool frozen){
    SlugMap *m=sv_map_new_raw(false,pairs); for(size_t i=0;i<pairs;i++) sv_map_put_raw(m,flat[i*2],flat[i*2+1]); m->frozen=frozen; return sv_map_value(m);
}

static SlugObject *sv_object_new(int class_id,const char *class_name){
    SlugObject *o=(SlugObject*)sv_heap_alloc(sizeof(SlugObject),SH_OBJECT);o->class_id=class_id;o->class_name=class_name;o->destroyed=false;o->len=0;o->cap=0;o->names=NULL;o->values=NULL;o->immutable=NULL;return o;
}
static int sv_object_find(SlugObject *o,const char *name){for(size_t i=0;i<o->len;i++)if(strcmp(o->names[i],name)==0)return (int)i;return -1;}
static void sv_object_reserve(SlugObject *o,size_t need){
    if(need<=o->cap)return;size_t cap=o->cap?o->cap*2:4;while(cap<need)cap*=2;
    o->names=(char**)sv_xrealloc(o->names,sizeof(char*)*cap);o->values=(SlugValue*)sv_xrealloc(o->values,sizeof(SlugValue)*cap);o->immutable=(bool*)sv_xrealloc(o->immutable,sizeof(bool)*cap);o->cap=cap;
}
static SlugObject *sv_as_object(SlugValue v){if(v.tag!=SV_OBJECT||!v.as.obj)sv_fail_kind("type","object value required");return v.as.obj;}
static SlugValue sv_object_get(SlugValue ov,const char *name){if(ov.tag==SV_ERROR&&ov.as.err){if(strcmp(name,"kind")==0)return ov.as.err->kind;if(strcmp(name,"message")==0)return ov.as.err->message;if(strcmp(name,"payload")==0)return ov.as.err->payload;if(strcmp(name,"cause")==0)return ov.as.err->cause;if(strcmp(name,"suppressed")==0)return ov.as.err->suppressed;sv_fail_kind("key","unknown error field");}SlugObject *o=sv_as_object(ov);int i=sv_object_find(o,name);if(i<0)sv_fail_kind("key","unknown object field");return o->values[i];}
static SlugValue sv_object_set(SlugValue ov,const char *name,SlugValue value,bool define,bool immutable,bool initialization){
    if(ov.tag==SV_ERROR)sv_fail_kind("immutable","error values are immutable");SlugObject *o=sv_as_object(ov);int i=sv_object_find(o,name);
    if(i<0){if(!define)sv_fail("unknown object field");sv_object_reserve(o,o->len+1);i=(int)o->len++;o->names[i]=sv_dup(name);o->values[i]=value;o->immutable[i]=immutable;return value;}
    if(o->immutable[i]&&!initialization)sv_fail("cannot assign immutable object field");o->values[i]=value;if(immutable)o->immutable[i]=true;return value;
}

/* v0.1.3 managed heap: lexical cells are roots while their scope is active, closures
   keep captured cells reachable, and graph tracing reclaims both acyclic and cyclic
   values.  No ownership syntax leaks into SLUG source. */
static SvHeap *sv_value_heap(SlugValue v){
    switch(v.tag){
        case SV_STRING:return v.as.s?&sv_string_header(v.as.s)->heap:NULL;
        case SV_BYTES:return v.as.bytes?&v.as.bytes->heap:NULL;
        case SV_SOCKET:return v.as.sock?&v.as.sock->heap:NULL;
        case SV_FILE:return v.as.file?&v.as.file->heap:NULL;
        case SV_SURFACE:return v.as.surface?&v.as.surface->heap:NULL;
        case SV_WINDOW:return v.as.window?&v.as.window->heap:NULL;
        case SV_AUDIO:return v.as.audio?&v.as.audio->heap:NULL;
        case SV_DEVICE:return v.as.device?&v.as.device->heap:NULL;
        case SV_LIST:return v.as.list?&v.as.list->heap:NULL;
        case SV_MAP:return v.as.map?&v.as.map->heap:NULL;
        case SV_OBJECT:return v.as.obj?&v.as.obj->heap:NULL;
        case SV_CALLABLE:return v.as.closure?&v.as.closure->heap:NULL;
        case SV_ERROR:return v.as.err?&v.as.err->heap:NULL;
        default:return NULL;
    }
}
typedef struct { SvHeap **items; size_t len,cap; } SvMarkStack;
static void sv_mark_push(SvMarkStack *st,SvHeap *h){if(!h||h->marked)return;if(st->len==st->cap){st->cap=st->cap?st->cap*2:32;st->items=(SvHeap**)sv_xrealloc(st->items,sizeof(SvHeap*)*st->cap);}st->items[st->len++]=h;}
static void sv_mark_value(SvMarkStack *st,SlugValue v){sv_mark_push(st,sv_value_heap(v));}
static void sv_mark_graph(SvMarkStack *st){
    while(st->len){SvHeap *h=st->items[--st->len];if(!h||h->marked)continue;h->marked=true;
        switch(h->kind){
            case SH_STRING:case SH_BYTES:case SH_SOCKET:case SH_FILE:case SH_SURFACE:case SH_WINDOW:case SH_AUDIO:case SH_DEVICE:break;
            case SH_CELL:{SlugCell *c=(SlugCell*)h;sv_mark_value(st,c->value);break;}
            case SH_LIST:{SlugList *l=(SlugList*)h;for(size_t i=0;i<l->len;i++)sv_mark_value(st,l->items[i]);break;}
            case SH_MAP:{SlugMap *m=(SlugMap*)h;for(size_t i=0;i<m->len;i++){sv_mark_value(st,m->keys[i]);sv_mark_value(st,m->vals[i]);}break;}
            case SH_OBJECT:{SlugObject *o=(SlugObject*)h;for(size_t i=0;i<o->len;i++)sv_mark_value(st,o->values[i]);break;}
            case SH_CLOSURE:{SlugClosure *c=(SlugClosure*)h;for(size_t i=0;i<c->capture_count;i++)sv_mark_push(st,&c->captures[i]->heap);break;}
            case SH_ERROR:{SlugErrorValue *e=(SlugErrorValue*)h;sv_mark_value(st,e->kind);sv_mark_value(st,e->message);sv_mark_value(st,e->payload);sv_mark_value(st,e->cause);sv_mark_value(st,e->suppressed);break;}
        }
    }
}
static void sv_gc_clear_marks(void){for(SvHeap *h=sv_heap_head;h;h=h->next)h->marked=false;}
static void sv_gc_mark_roots(void){
    SvMarkStack st={0};
    for(SvHeap *h=sv_heap_head;h;h=h->next)if(h->kind==SH_CELL&&((SlugCell*)h)->permanent_root)sv_mark_push(&st,h);
    for(SlugScopeFrame *f=sv_scope_top;f;f=f->prev)for(size_t i=0;i<f->len;i++){SlugCell *c=f->cells[i];if(c->heap_owned)sv_mark_push(&st,&c->heap);else sv_mark_value(&st,c->value);}
    for(size_t i=0;i<sv_root_slots_len;i++)if(sv_root_slots[i])sv_mark_value(&st,*sv_root_slots[i]);
    for(SvLocalRootFrame *f=sv_local_root_top;f;f=f->prev)for(size_t i=0;i<f->len;i++)if(f->slots[i])sv_mark_value(&st,*f->slots[i]);
    for(size_t i=0;i<sv_temp_roots_len;i++)sv_mark_value(&st,sv_temp_roots[i]);
    for(size_t i=0;i<sv_literal_intern_cap;i++)if(sv_literal_intern[i].str)sv_mark_push(&st,&sv_literal_intern[i].str->heap);
    for(SlugExcFrame *f=sv_exc_top;f;f=f->prev)sv_mark_value(&st,f->error);
    sv_mark_graph(&st);free(st.items);
}
static void sv_heap_free_node(SvHeap *h){
    sv_heap_unlink(h);
    switch(h->kind){
        case SH_STRING:free((SlugString*)h);break;
        case SH_BYTES:{SlugBytes *b=(SlugBytes*)h;free(b->data);free(b);break;}
        case SH_SOCKET:{SlugSocket *s=(SlugSocket*)h;sv_socket_close_raw(s);free(s);break;}
        case SH_FILE:{SlugFile *f=(SlugFile*)h;sv_file_close_raw(f);free(f);break;}
        case SH_SURFACE:{SlugSurface *x=(SlugSurface*)h;free(x->pixels);free(x);break;}
        case SH_WINDOW:{SlugWindow *x=(SlugWindow*)h;sv_window_close_raw(x);free(x);break;}
        case SH_AUDIO:{SlugAudio *x=(SlugAudio*)h;sv_audio_close_raw(x);free(x);break;}
        case SH_DEVICE:{SlugDevice *x=(SlugDevice*)h;sv_device_close_raw(x);free(x);break;}
        case SH_CELL:free((SlugCell*)h);break;
        case SH_LIST:{SlugList *l=(SlugList*)h;free(l->items);free(l);break;}
        case SH_MAP:{SlugMap *m=(SlugMap*)h;free(m->keys);free(m->vals);free(m);break;}
        case SH_OBJECT:{SlugObject *o=(SlugObject*)h;for(size_t i=0;i<o->len;i++)free(o->names[i]);free(o->names);free(o->values);free(o->immutable);free(o);break;}
        case SH_CLOSURE:{SlugClosure *c=(SlugClosure*)h;free(c->captures);free(c);break;}
        case SH_ERROR:free((SlugErrorValue*)h);break;
    }
}
static bool sv_run_finalizer(SlugObject *o,bool shutdown_mode,SlugValue *escaped){
    if(!o||o->destroyed||!sv_object_destructor)return true;
    /* Mark before invocation: resurrection is allowed, re-finalization is not. */
    o->destroyed=true;
    size_t root=sv_temp_root_push(sv_object_value(o));
    SlugExcFrame isolated={0};sv_exc_push(&isolated);
    if(setjmp(isolated.env)==0){
        sv_object_destructor(o);sv_exc_pop(&isolated);sv_temp_root_pop(root);return true;
    }
    SlugValue err=isolated.error;sv_exc_pop(&isolated);sv_temp_root_pop(root);
    if(escaped)*escaped=err;
    (void)shutdown_mode;return false;
}
static void sv_gc_collect(void){
    if(sv_gc_running||sv_runtime_stopped)return;sv_gc_running=true;sv_gc_collections++;
    sv_gc_clear_marks();sv_gc_mark_roots();
    bool finalized=false;
    if(sv_object_destructor){
        for(SvHeap *h=sv_heap_head;h;h=h->next)if(!h->marked&&h->kind==SH_OBJECT&&!((SlugObject*)h)->destroyed){
            SlugValue ferr=sv_null();
            if(!sv_run_finalizer((SlugObject*)h,false,&ferr)){
                sv_gc_running=false;fputs("SLUG uncaught finalizer error: ",stderr);sv_report_uncaught(ferr);exit(66);
            }
            finalized=true;
        }
    }
    if(finalized){sv_gc_clear_marks();sv_gc_mark_roots();}
    SvHeap *h=sv_heap_head;while(h){SvHeap *next=h->next;if(!h->marked)sv_heap_free_node(h);else h->marked=false;h=next;}
    sv_gc_running=false;
}
static void sv_gc_safepoint(void){
    if(sv_runtime_stopped)return;
    if(!sv_gc_policy_loaded){
        sv_gc_policy_loaded=true;
        const char *raw=getenv("SLUG_GC_INTERVAL");
        if(raw&&raw[0]){
            char *end=NULL; unsigned long long parsed=strtoull(raw,&end,10);
            if(end!=raw&&end&&*end=='\0'&&parsed>0){
                sv_gc_interval=parsed>(unsigned long long)SIZE_MAX?SIZE_MAX:(size_t)parsed;
                if(!sv_gc_interval)sv_gc_interval=1;
            }
        }
    }
    sv_gc_safepoints++;
    if(sv_gc_safepoints>=sv_gc_interval){sv_gc_safepoints=0;sv_gc_collect();}
}
static void sv_runtime_shutdown(void){
    if(sv_runtime_stopped)return;sv_gc_running=true;
    if(sv_object_destructor){for(SvHeap *h=sv_heap_head;h;h=h->next)if(h->kind==SH_OBJECT&&!((SlugObject*)h)->destroyed){SlugValue ferr=sv_null();if(!sv_run_finalizer((SlugObject*)h,true,&ferr)){fputs("SLUG finalizer error during shutdown: ",stderr);sv_report_uncaught(ferr);}}}
    while(sv_heap_head)sv_heap_free_node(sv_heap_head);
    while(sv_scope_top){SlugScopeFrame *f=sv_scope_top;sv_scope_top=f->prev;free(f->cells);f->cells=NULL;}
    free(sv_root_slots);sv_root_slots=NULL;sv_root_slots_len=sv_root_slots_cap=0;free(sv_temp_roots);sv_temp_roots=NULL;sv_temp_roots_len=sv_temp_roots_cap=0;
    free(sv_literal_intern);sv_literal_intern=NULL;sv_literal_intern_cap=sv_literal_intern_len=0;
#ifdef _WIN32
    WSACleanup();
#endif
    sv_runtime_stopped=true;sv_gc_running=false;
    const char *report=getenv("SLUG_HEAP_REPORT");if(report&&report[0]&&strcmp(report,"0")!=0)fprintf(stderr,"SLUG heap: allocated=%zu freed=%zu live=%zu peak=%zu collections=%zu\n",sv_heap_allocated,sv_heap_freed,sv_heap_allocated-sv_heap_freed,sv_heap_peak,sv_gc_collections);
}
static void sv_runtime_init(void){
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);SetConsoleCP(CP_UTF8);WSADATA wsa;if(WSAStartup(MAKEWORD(2,2),&wsa)!=0)sv_fail("Winsock initialization failed");
#endif
    atexit(sv_runtime_shutdown);
}
static void sv_fail(const char *msg){sv_fail_kind("state",msg);}

typedef struct { char *p; size_t n,cap; } SvBuf;
static void sb_init(SvBuf *b){b->cap=64;b->n=0;b->p=(char*)sv_xmalloc(b->cap);b->p[0]=0;}
static void sb_need(SvBuf *b,size_t add){size_t need=b->n+add+1;if(need<=b->cap)return;while(b->cap<need)b->cap=b->cap<32?64:b->cap*2;b->p=(char*)sv_xrealloc(b->p,b->cap);}
static void sb_add_n(SvBuf *b,const void *p,size_t n){if(!n)return;sb_need(b,n);memcpy(b->p+b->n,p,n);b->n+=n;b->p[b->n]=0;}
static void sb_add(SvBuf *b,const char *x){sb_add_n(b,x,strlen(x));}
static void sb_ch(SvBuf *b,char c){sb_need(b,1);b->p[b->n++]=c;b->p[b->n]=0;}
static void sb_u64(SvBuf *b,uint64_t x){char t[32];int n=snprintf(t,sizeof(t),"%" PRIu64,x);if(n>0)sb_add_n(b,t,(size_t)n);}
static void sb_i64(SvBuf *b,int64_t x){char t[32];int n=snprintf(t,sizeof(t),"%" PRId64,x);if(n>0)sb_add_n(b,t,(size_t)n);}
static void sb_f64(SvBuf *b,double x){char t[64];int n=snprintf(t,sizeof(t),"%.17g",x);if(n>0)sb_add_n(b,t,(size_t)n);}
static void sb_quote_string(SvBuf *b,const char *s,size_t n){sb_ch(b,'\'');if(s){for(size_t i=0;i<n;i++){unsigned char c=(unsigned char)s[i];switch(c){case '\\':sb_add(b,"\\\\");break;case '\'':sb_add(b,"\\\'");break;case '\n':sb_add(b,"\\n");break;case '\r':sb_add(b,"\\r");break;case '\t':sb_add(b,"\\t");break;case 0:sb_add(b,"\\0");break;default:sb_ch(b,(char)c);break;}}}sb_ch(b,'\'');}
typedef enum {SFT_VALUE,SFT_TEXT,SFT_CHAR,SFT_LEAVE} SvFmtKind;
typedef struct {SvFmtKind kind;SlugValue value;const char *text;char ch;SlugTag tag;const void *ptr;bool nested;} SvFmtTask;
typedef struct {SvFmtTask *p;size_t n,cap;} SvFmtTasks;
typedef struct {SlugTag tag;const void *ptr;} SvActiveItem;
typedef struct {SvActiveItem *p;size_t n,cap;} SvActive;
static void sft_push(SvFmtTasks *q,SvFmtTask t){if(q->n==q->cap){q->cap=q->cap?q->cap*2:32;q->p=(SvFmtTask*)sv_xrealloc(q->p,sizeof(SvFmtTask)*q->cap);}q->p[q->n++]=t;}
static void sft_value(SvFmtTasks *q,SlugValue v,bool nested){SvFmtTask t={0};t.kind=SFT_VALUE;t.value=v;t.nested=nested;sft_push(q,t);}
static void sft_text(SvFmtTasks *q,const char *x){SvFmtTask t={0};t.kind=SFT_TEXT;t.text=x;sft_push(q,t);}
static void sft_char(SvFmtTasks *q,char x){SvFmtTask t={0};t.kind=SFT_CHAR;t.ch=x;sft_push(q,t);}
static void sft_leave(SvFmtTasks *q,SlugTag tag,const void *ptr){SvFmtTask t={0};t.kind=SFT_LEAVE;t.tag=tag;t.ptr=ptr;sft_push(q,t);}
static bool sva_contains(SvActive *a,SlugTag tag,const void *ptr){for(size_t i=0;i<a->n;i++)if(a->p[i].tag==tag&&a->p[i].ptr==ptr)return true;return false;}
static void sva_push(SvActive *a,SlugTag tag,const void *ptr){if(a->n==a->cap){a->cap=a->cap?a->cap*2:16;a->p=(SvActiveItem*)sv_xrealloc(a->p,sizeof(SvActiveItem)*a->cap);}a->p[a->n++]=(SvActiveItem){tag,ptr};}
static void sva_leave(SvActive *a,SlugTag tag,const void *ptr){if(!a->n||a->p[a->n-1].tag!=tag||a->p[a->n-1].ptr!=ptr)sv_fail("format active stack corruption");a->n--;}
static void sv_format_into(SvBuf *b,SlugValue root){
    SvFmtTasks q={0};SvActive active={0};sft_value(&q,root,false);
    while(q.n){SvFmtTask t=q.p[--q.n];if(t.kind==SFT_TEXT){sb_add(b,t.text);continue;}if(t.kind==SFT_CHAR){sb_ch(b,t.ch);continue;}if(t.kind==SFT_LEAVE){sva_leave(&active,t.tag,t.ptr);continue;}SlugValue v=t.value;
        switch(v.tag){
            case SV_NULL:sb_add(b,"nn");break;case SV_BOOL:sb_add(b,v.as.b?"true":"false");break;case SV_INT:sb_i64(b,v.as.i);break;case SV_UINT:sb_u64(b,v.as.u);break;case SV_FLOAT:sb_f64(b,v.as.f);break;
            case SV_STRING:{size_t n=sv_string_bytes(v.as.s);if(t.nested)sb_quote_string(b,v.as.s?v.as.s:"",n);else if(n)sb_add_n(b,v.as.s,n);break;}
            case SV_BYTES:{sb_add(b,"0x");static const char hx[]="0123456789ABCDEF";if(v.as.bytes)for(size_t i=0;i<v.as.bytes->len;i++){unsigned char x=v.as.bytes->data[i];sb_ch(b,hx[x>>4]);sb_ch(b,hx[x&15]);}break;}
            case SV_SOCKET:sb_add(b,v.as.sock&&v.as.sock->closed?"socket(closed)":"socket");break;case SV_FILE:sb_add(b,v.as.file&&v.as.file->closed?"file(closed)":"file");break;case SV_SURFACE:sb_add(b,"surface");break;case SV_WINDOW:sb_add(b,v.as.window&&v.as.window->closed?"window(closed)":"window");break;case SV_AUDIO:sb_add(b,v.as.audio&&v.as.audio->closed?"audio(closed)":"audio");break;case SV_DEVICE:sb_add(b,v.as.device&&v.as.device->closed?"device(closed)":"device");break;
            case SV_CALLABLE:sb_add(b,"callable");break;case SV_DEFAULT:sb_add(b,"xx");break;case SV_OBJECT:sb_add(b,v.as.obj&&v.as.obj->class_name?v.as.obj->class_name:"object");break;
            case SV_LIST:{SlugList *x=v.as.list;if(!x){sb_add(b,"[]");break;}if(sva_contains(&active,SV_LIST,x)){sb_add(b,"<cycle>");break;}sva_push(&active,SV_LIST,x);sb_ch(b,'[');sft_leave(&q,SV_LIST,x);sft_char(&q,']');for(size_t i=x->len;i>0;i--){if(i<x->len)sft_char(&q,',');sft_value(&q,x->items[i-1],true);}break;}
            case SV_MAP:{SlugMap *x=v.as.map;if(!x){sb_add(b,"[:]");break;}if(sva_contains(&active,SV_MAP,x)){sb_add(b,"<cycle>");break;}sva_push(&active,SV_MAP,x);sb_ch(b,'[');sft_leave(&q,SV_MAP,x);sft_char(&q,']');for(size_t i=x->len;i>0;i--){if(i<x->len)sft_char(&q,',');sft_value(&q,x->vals[i-1],true);sft_char(&q,':');sft_value(&q,x->keys[i-1],true);}break;}
            case SV_ERROR:{SlugErrorValue *x=v.as.err;if(!x){sb_add(b,"ER()");break;}if(sva_contains(&active,SV_ERROR,x)){sb_add(b,"<cycle>");break;}sva_push(&active,SV_ERROR,x);sb_add(b,"ER(");sft_leave(&q,SV_ERROR,x);sft_char(&q,')');sft_value(&q,x->suppressed,true);sft_text(&q,", suppressed=");sft_value(&q,x->cause,true);sft_text(&q,", cause=");sft_value(&q,x->payload,true);sft_text(&q,", payload=");sft_value(&q,x->message,true);sft_text(&q,", message=");sft_value(&q,x->kind,true);sft_text(&q,"kind=");break;}
        }
    }
    free(q.p);free(active.p);
}
static char *sv_to_cstr(SlugValue v){SvBuf b;sb_init(&b);sv_format_into(&b,v);return b.p;}
static void sv_report_uncaught(SlugValue e){SvBuf b;sb_init(&b);sv_format_into(&b,e);fwrite(b.p,1,b.n,stderr);fputc('\n',stderr);free(b.p);}
static void sv_fail_kind(const char *kind,const char *msg){sv_raise(sv_error_new(kind,msg,sv_null(),sv_null(),sv_null()));}

static SlugValue sv_add(SlugValue a,SlugValue b){
    if(a.tag==SV_BYTES||b.tag==SV_BYTES){if(a.tag!=SV_BYTES||b.tag!=SV_BYTES)sv_fail("bytes concatenate requires bytes operands");size_t n=a.as.bytes->len+b.as.bytes->len;unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;if(a.as.bytes->len)memcpy(p,a.as.bytes->data,a.as.bytes->len);if(b.as.bytes->len)memcpy(p+a.as.bytes->len,b.as.bytes->data,b.as.bytes->len);SlugValue v=sv_bytes(p,n);free(p);return v;}
    if(a.tag==SV_STRING||b.tag==SV_STRING){if(a.tag!=SV_STRING||b.tag!=SV_STRING)sv_fail_kind("type","string concatenation requires string + string");size_t na=sv_string_bytes(a.as.s),nb=sv_string_bytes(b.as.s);if(na>SIZE_MAX-nb)sv_fail_kind("resource","string size overflow");size_t n=na+nb;unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;if(na)memcpy(p,a.as.s,na);if(nb)memcpy(p+na,b.as.s,nb);SlugValue v=sv_string_n(p,n);free(p);return v;}
    if(a.tag==SV_FLOAT||b.tag==SV_FLOAT)return sv_float(sv_num(a)+sv_num(b));
    return sv_wadd(sv_wint(a),sv_wint(b));
}
static SlugValue sv_sub(SlugValue a,SlugValue b){if(a.tag==SV_FLOAT||b.tag==SV_FLOAT)return sv_float(sv_num(a)-sv_num(b));return sv_wsub(sv_wint(a),sv_wint(b));}
static SlugValue sv_mul(SlugValue a,SlugValue b){if(a.tag==SV_FLOAT||b.tag==SV_FLOAT)return sv_float(sv_num(a)*sv_num(b));return sv_wmul(sv_wint(a),sv_wint(b));}
static SlugValue sv_div(SlugValue a,SlugValue b){double d=sv_num(b);if(d==0.0)sv_fail("division by zero");return sv_float(sv_num(a)/d);}
static SlugValue sv_idiv(SlugValue a,SlugValue b){SvWideInt x=sv_wint(a),y=sv_wint(b);if(y.mag==0)sv_fail("integer division by zero");uint64_t q=x.mag/y.mag;bool neg=(x.neg!=y.neg)&&q!=0;return sv_wint_value(neg,q,(x.prefer_unsigned||y.prefer_unsigned)&&!neg);}
static SlugValue sv_mod(SlugValue a,SlugValue b){SvWideInt x=sv_wint(a),y=sv_wint(b);if(y.mag==0)sv_fail("remainder by zero");uint64_t r=x.mag%y.mag;return sv_wint_value(x.neg,r,x.prefer_unsigned&&!x.neg);}
static SlugValue sv_pow(SlugValue a,SlugValue b){
    if(a.tag==SV_FLOAT||b.tag==SV_FLOAT){double x=sv_num(a),y=sv_num(b);if(x==0.0&&y<0.0)sv_fail("zero to negative exponent");if(x==0.0&&y==0.0)return sv_int(1);return sv_float(pow(x,y));}
    SvWideInt e=sv_wint(b);if(e.neg){double x=sv_num(a),y=-(double)e.mag;if(x==0.0)sv_fail("zero to negative exponent");return sv_float(pow(x,y));}
    if((a.tag==SV_INT&&a.as.i==0)||(a.tag==SV_UINT&&a.as.u==0)){if(e.mag==0)return sv_int(1);}
    SlugValue r=sv_int(1),base=a;uint64_t n=e.mag;while(n){if(n&1)r=sv_mul(r,base);n>>=1;if(n)base=sv_mul(base,base);}return r;
}
static SlugValue sv_neg(SlugValue a){if(a.tag==SV_FLOAT)return sv_float(-a.as.f);SvWideInt x=sv_wint(a);x.neg=!x.neg;return sv_wint_value(x.neg,x.mag,false);}
static void sv_require_range_bound(SlugValue v){if(v.tag!=SV_INT&&v.tag!=SV_UINT)sv_fail("range bound must be integer");}
static SlugValue sv_range_next(SlugValue v,bool allow_unsigned){if(v.tag==SV_UINT){if(v.as.u==UINT64_MAX)sv_fail("range iterator overflow");return sv_uint(v.as.u+1);}if(v.tag!=SV_INT)sv_fail("range bound must be integer");if(v.as.i==INT64_MAX){if(allow_unsigned)return sv_uint((uint64_t)INT64_MAX+1u);sv_fail("range iterator overflow");}return sv_int(v.as.i+1);}
static bool sv_ascii_space(unsigned char c){return c==' '||c=='\t'||c=='\n'||c=='\r'||c=='\f'||c=='\v';}
static void sv_trim_ascii(const char *s,const char **start,const char **end){const char *a=s?s:"",*b=a+strlen(a);while(a<b&&sv_ascii_space((unsigned char)*a))a++;while(b>a&&sv_ascii_space((unsigned char)b[-1]))b--;*start=a;*end=b;}
static bool sv_parse_dec_wide(const char *s,bool allow_negative,SvWideInt *out){
    const char *p,*e;sv_trim_ascii(s,&p,&e);if(p==e)return false;bool neg=false;if(*p=='+'||*p=='-'){neg=*p=='-';p++;if(p==e)return false;}if(neg&&!allow_negative)return false;
    uint64_t mag=0;for(;p<e;p++){unsigned char c=(unsigned char)*p;if(c<'0'||c>'9')return false;unsigned d=(unsigned)(c-'0');if(mag>(UINT64_MAX-d)/10)return false;mag=mag*10+d;}
    out->neg=neg&&mag!=0;out->mag=mag;out->prefer_unsigned=!out->neg;return true;
}
static bool sv_valid_decimal_float_span(const char *p,const char *e){
    if(p==e)return false;if(*p=='+'||*p=='-'){p++;if(p==e)return false;}bool before=false,after=false;while(p<e&&*p>='0'&&*p<='9'){before=true;p++;}
    if(p<e&&*p=='.'){p++;while(p<e&&*p>='0'&&*p<='9'){after=true;p++;}}if(!before&&!after)return false;
    if(p<e&&(*p=='e'||*p=='E')){p++;if(p<e&&(*p=='+'||*p=='-'))p++;const char *q=p;while(p<e&&*p>='0'&&*p<='9')p++;if(p==q)return false;}return p==e;
}
static bool sv_parse_dec_float(const char *s,double *out){
    const char *a,*e;sv_trim_ascii(s,&a,&e);if(!sv_valid_decimal_float_span(a,e))return false;size_t n=(size_t)(e-a);char *buf=(char*)sv_xmalloc(n+1);memcpy(buf,a,n);buf[n]='\0';errno=0;char *z=NULL;double v=strtod(buf,&z);bool ok=z==buf+n&&errno!=ERANGE&&isfinite(v);free(buf);if(!ok)return false;*out=v;return true;
}
static bool sv_text_to_i64(const char *s,int64_t *out){
    SvWideInt w;if(!sv_parse_dec_wide(s,true,&w))return false;if((!w.neg&&w.mag>(uint64_t)INT64_MAX)||(w.neg&&w.mag>UINT64_C(9223372036854775808)))return false;
    if(w.neg){if(w.mag==UINT64_C(9223372036854775808))*out=INT64_MIN;else *out=-(int64_t)w.mag;}else *out=(int64_t)w.mag;return true;
}
static bool sv_text_to_u64(const char *s,uint64_t *out){SvWideInt w;if(!sv_parse_dec_wide(s,false,&w))return false;*out=w.mag;return true;}
static bool sv_text_to_float(const char *s,double *out){return sv_parse_dec_float(s,out);}

static SlugValue sv_cast_i_width(SlugValue a,int bits){
    int64_t sx=0;
    if(a.tag==SV_STRING){if(!sv_text_to_i64(a.as.s?a.as.s:"",&sx))sv_fail("string is not a decimal numeric value");a=sv_int(sx);}
    if(a.tag==SV_FLOAT){int64_t x=sv_i64_numeric(a);if(bits>0&&bits<64){int64_t lo=-(INT64_C(1)<<(bits-1)),hi=(INT64_C(1)<<(bits-1))-1;if(x<lo||x>hi)sv_fail("signed integer cast out of range");}return sv_int(x);}
    SvWideInt w=sv_wint(a);uint64_t poshi=bits>=64?(uint64_t)INT64_MAX:((UINT64_C(1)<<(bits-1))-1);uint64_t negmag=bits>=64?UINT64_C(9223372036854775808):(UINT64_C(1)<<(bits-1));
    if((!w.neg&&w.mag>poshi)||(w.neg&&w.mag>negmag))sv_fail("signed integer cast out of range");
    return sv_wint_value(w.neg,w.mag,false);
}
static SlugValue sv_cast_u_width(SlugValue a,int bits){
    uint64_t parsed=0;if(a.tag==SV_STRING){if(!sv_text_to_u64(a.as.s?a.as.s:"",&parsed))sv_fail("string is not a nonnegative decimal numeric value");a=sv_uint(parsed);}
    uint64_t x=sv_u64_numeric(a);if(bits>0&&bits<64){uint64_t hi=(UINT64_C(1)<<bits)-1;if(x>hi)sv_fail("unsigned integer cast out of range");}
    return sv_uint(x);
}
static SlugValue sv_cast_i(SlugValue a){return sv_cast_i_width(a,64);}
static SlugValue sv_cast_u(SlugValue a){return sv_cast_u_width(a,64);}
static SlugValue sv_cast_f(SlugValue a){if(a.tag==SV_STRING){double x=0;if(!sv_text_to_float(a.as.s?a.as.s:"",&x))sv_fail("string is not a decimal numeric value");return sv_float(x);}return sv_float(sv_num(a));}
static SlugValue sv_cast_b(SlugValue a){return sv_bool(sv_truthy(a));}
static SlugValue sv_cast_s(SlugValue a){if(a.tag==SV_STRING)return a;if(a.tag==SV_BYTES){if(!sv_utf8_valid(a.as.bytes->data,a.as.bytes->len))sv_fail_kind("encoding","bytes are not valid UTF-8");return sv_string_n(a.as.bytes->data,a.as.bytes->len);}SvBuf b;sb_init(&b);sv_format_into(&b,a);SlugValue v=sv_string_n((const unsigned char*)b.p,b.n);free(b.p);return v;}

typedef struct { char base; int bits; bool valid; } SvTypeDesc;
static SvTypeDesc sv_type_desc_text(const char *s){
    SvTypeDesc d={0,0,false};if(!s||!*s)return d;d.base=s[0];if(!strchr("iufsb",d.base))return d;const char *w=s+1;
    if(d.base=='s'||d.base=='b'){if(*w)return d;d.bits=0;d.valid=true;return d;}
    if(!*w){d.bits=(d.base=='f'?64:64);d.valid=true;return d;}
    char *e=NULL;long n=strtol(w,&e,10);if(!e||*e)return d;
    if((d.base=='i'||d.base=='u')&&(n==8||n==16||n==32||n==64)){d.bits=(int)n;d.valid=true;return d;}
    if(d.base=='f'&&(n==16||n==32||n==64||n==128)){d.bits=(int)n;d.valid=true;return d;}
    return d;
}
static bool sv_can_cast_desc(SvTypeDesc d,SlugValue a){
    if(!d.valid||a.tag==SV_DEFAULT)return false;
    if(d.base=='s'){
        if(a.tag!=SV_BYTES)return true;
        if(!a.as.bytes)return true;
        for(size_t i=0;i<a.as.bytes->len;i++)if(a.as.bytes->data[i]==0)return false;
        return sv_utf8_valid(a.as.bytes->data,a.as.bytes->len);
    }
    if(d.base=='b')return true;
    if(d.base=='f'){
        if(a.tag==SV_INT||a.tag==SV_UINT||a.tag==SV_FLOAT||a.tag==SV_BOOL)return true;
        double x=0;return a.tag==SV_STRING&&sv_text_to_float(a.as.s?a.as.s:"",&x);
    }
    if(d.base=='i'){
        int64_t x=0;if(a.tag==SV_STRING){if(!sv_text_to_i64(a.as.s?a.as.s:"",&x))return false;}
        else if(a.tag==SV_INT)x=a.as.i;
        else if(a.tag==SV_UINT){if(a.as.u>(uint64_t)INT64_MAX)return false;x=(int64_t)a.as.u;}
        else if(a.tag==SV_BOOL)x=a.as.b?1:0;
        else if(a.tag==SV_FLOAT){if(!isfinite(a.as.f)||a.as.f < -9223372036854775808.0 || a.as.f >= 9223372036854775808.0)return false;x=(int64_t)a.as.f;}
        else return false;
        int bits=d.bits?d.bits:64;if(bits<64){int64_t lo=-(INT64_C(1)<<(bits-1)),hi=(INT64_C(1)<<(bits-1))-1;if(x<lo||x>hi)return false;}return true;
    }
    if(d.base=='u'){
        uint64_t x=0;if(a.tag==SV_STRING){if(!sv_text_to_u64(a.as.s?a.as.s:"",&x))return false;}
        else if(a.tag==SV_UINT)x=a.as.u;
        else if(a.tag==SV_INT){if(a.as.i<0)return false;x=(uint64_t)a.as.i;}
        else if(a.tag==SV_BOOL)x=a.as.b?1u:0u;
        else if(a.tag==SV_FLOAT){if(!isfinite(a.as.f)||a.as.f<0.0||a.as.f>=18446744073709551616.0)return false;x=(uint64_t)a.as.f;}
        else return false;
        int bits=d.bits?d.bits:64;if(bits<64){uint64_t hi=(UINT64_C(1)<<bits)-1;if(x>hi)return false;}return true;
    }
    return false;
}
static SlugValue sv_cast_dynamic(SlugValue typev,SlugValue value){
    if(typev.tag!=SV_STRING)sv_fail("dynamic cast type must be a type string");SvTypeDesc d=sv_type_desc_text(typev.as.s?typev.as.s:"");if(!d.valid)sv_fail("invalid dynamic cast type");
    if(d.base=='i')return sv_cast_i_width(value,d.bits?d.bits:64);
    if(d.base=='u')return sv_cast_u_width(value,d.bits?d.bits:64);
    if(d.base=='f')return sv_cast_f(value);
    if(d.base=='s')return sv_cast_s(value);
    return sv_cast_b(value);
}
static SlugValue sv_typeof_value(SlugValue v){
    switch(v.tag){
        case SV_NULL:return sv_string("null");case SV_INT:return sv_string("i");case SV_UINT:return sv_string("u");case SV_FLOAT:return sv_string("f");case SV_STRING:return sv_string("s");case SV_BYTES:return sv_string("bytes");
        case SV_SOCKET:return sv_string("socket");case SV_FILE:return sv_string("file");case SV_SURFACE:return sv_string("surface");case SV_WINDOW:return sv_string("window");case SV_AUDIO:return sv_string("audio");case SV_DEVICE:return sv_string("device");
        case SV_BOOL:return sv_string("b");case SV_LIST:return sv_string("list");case SV_MAP:return sv_string("map");case SV_CALLABLE:return sv_string("callable");case SV_ERROR:return sv_string("error");case SV_DEFAULT:return sv_string("default");
        case SV_OBJECT:{const char *n=(v.as.obj&&v.as.obj->class_name)?v.as.obj->class_name:"object";size_t k=strlen(n);char *p=(char*)sv_xmalloc(k+8);memcpy(p,"object:",7);memcpy(p+7,n,k+1);return sv_string_owned(p);}
    }
    return sv_string("unknown");
}
static SlugValue sv_can_convert_value(SlugValue typev,SlugValue value){if(typev.tag!=SV_STRING)return sv_bool(false);return sv_bool(sv_can_cast_desc(sv_type_desc_text(typev.as.s?typev.as.s:""),value));}
static SlugValue sv_inc(SlugValue a){return sv_add(a,sv_int(1));}
static SlugValue sv_dec(SlugValue a){return sv_sub(a,sv_int(1));}

static int64_t sv_len_i(SlugValue v){
    if(v.tag==SV_STRING)return (int64_t)sv_string_cps(v.as.s);
    if(v.tag==SV_BYTES)return (int64_t)v.as.bytes->len;
    if(v.tag==SV_LIST)return (int64_t)v.as.list->len;
    if(v.tag==SV_MAP)return (int64_t)v.as.map->len;
    sv_fail("ln requires string/bytes/list/map");return 0;
}
static int64_t sv_norm_index(int64_t i,int64_t n){if(i<0)i+=n;if(i<0||i>=n)sv_fail("index out of range");return i;}
static SlugValue sv_index(SlugValue base,SlugValue index){
    if(base.tag==SV_LIST){int64_t i=sv_norm_index(sv_int_num(index),(int64_t)base.as.list->len);return base.as.list->items[i];}
    if(base.tag==SV_BYTES){int64_t i=sv_norm_index(sv_int_num(index),(int64_t)base.as.bytes->len);return sv_uint(base.as.bytes->data[i]);}
    if(base.tag==SV_STRING){const char *s=base.as.s?base.as.s:"";size_t bytes=sv_string_bytes(base.as.s);int64_t n=(int64_t)sv_string_cps(base.as.s);int64_t k=sv_norm_index(sv_int_num(index),n);if(sv_string_ascii(base.as.s))return sv_string_n((const unsigned char*)s+(size_t)k,1);size_t a=sv_utf8_offset_n(s,bytes,(size_t)k),b=sv_utf8_offset_n(s,bytes,(size_t)k+1);return sv_string_n((const unsigned char*)s+a,b-a);}
    if(base.tag==SV_MAP){int i=sv_map_find(base.as.map,index);if(i<0)sv_fail("missing map key");return base.as.map->vals[i];}
    sv_fail("value is not indexable");return sv_null();
}
static int64_t sv_clamp_pos(int64_t x,int64_t n){if(x<0)x+=n;if(x<0)x=0;if(x>n)x=n;return x;}
static SlugValue sv_slice(SlugValue base,SlugValue startv,SlugValue stopv,SlugValue stepv){
    if(base.tag!=SV_LIST&&base.tag!=SV_STRING&&base.tag!=SV_BYTES)sv_fail("slice requires list/string/bytes");
    int64_t n=sv_len_i(base);int64_t step=stepv.tag==SV_NULL?1:sv_int_num(stepv);if(step==0)sv_fail("zero slice step");
    int64_t start,stop;
    if(step>0){start=startv.tag==SV_NULL?0:sv_clamp_pos(sv_int_num(startv),n);stop=stopv.tag==SV_NULL?n:sv_clamp_pos(sv_int_num(stopv),n);}else{
        if(startv.tag==SV_NULL)start=n-1;else{start=sv_int_num(startv);if(start<0)start+=n;if(start<0)start=-1;if(start>=n)start=n-1;}
        if(stopv.tag==SV_NULL)stop=-1;else{stop=sv_int_num(stopv);if(stop<0)stop+=n;if(stop<0)stop=-1;if(stop>=n)stop=n-1;}
    }
    size_t count=0;for(int64_t i=start;step>0?i<stop:i>stop;i+=step)count++;
    if(base.tag==SV_LIST){SlugList *l=sv_list_new_raw(base.as.list->frozen,count);size_t j=0;for(int64_t i=start;step>0?i<stop:i>stop;i+=step)l->items[j++]=base.as.list->items[i];return sv_list_value(l);}
    if(base.tag==SV_BYTES){unsigned char *p=count?(unsigned char*)sv_xmalloc(count):NULL;size_t j=0;for(int64_t i=start;step>0?i<stop:i>stop;i+=step)p[j++]=base.as.bytes->data[i];SlugValue v=sv_bytes(p,count);free(p);return v;}
    const char *s=base.as.s?base.as.s:"";size_t bytes=sv_string_bytes(base.as.s);SvBuf b;sb_init(&b);if(sv_string_ascii(base.as.s)){for(int64_t i=start;step>0?i<stop:i>stop;i+=step)sb_ch(&b,s[i]);}else{for(int64_t i=start;step>0?i<stop:i>stop;i+=step){size_t x=sv_utf8_offset_n(s,bytes,(size_t)i),y=sv_utf8_offset_n(s,bytes,(size_t)i+1);sb_add_n(&b,s+x,y-x);}}SlugValue out=sv_string_n((const unsigned char*)b.p,b.n);free(b.p);return out;
}
static SlugValue sv_set_index(SlugValue base,SlugValue index,SlugValue value,bool create){
    if(base.tag==SV_LIST){if(base.as.list->frozen)sv_fail("cannot mutate frozen list");int64_t i=sv_norm_index(sv_int_num(index),(int64_t)base.as.list->len);base.as.list->items[i]=value;return value;}
    if(base.tag==SV_MAP){if(base.as.map->frozen)sv_fail("cannot mutate frozen map");int i=sv_map_find(base.as.map,index);if(i<0){if(!create)sv_fail("missing map key");sv_map_put_raw(base.as.map,index,value);}else base.as.map->vals[i]=value;return value;}
    if(base.tag==SV_STRING)sv_fail("strings are immutable");sv_fail("indexed assignment requires list/map");return sv_null();
}
static SlugValue sv_in(SlugValue needle,SlugValue hay){
    if(hay.tag==SV_BYTES){uint64_t x=sv_u64_numeric(needle);if(x>255)sv_fail("byte membership value out of range");for(size_t i=0;i<hay.as.bytes->len;i++)if(hay.as.bytes->data[i]==(unsigned char)x)return sv_bool(true);return sv_bool(false);}
    if(hay.tag==SV_LIST){for(size_t i=0;i<hay.as.list->len;i++)if(sv_equal(needle,hay.as.list->items[i]))return sv_bool(true);return sv_bool(false);}
    if(hay.tag==SV_STRING){if(needle.tag!=SV_STRING)sv_fail_kind("type","string membership requires string needle");size_t hn=sv_string_bytes(hay.as.s),nn=sv_string_bytes(needle.as.s);if(!nn)return sv_bool(true);if(nn>hn)return sv_bool(false);for(size_t i=0;i+nn<=hn;i++)if(memcmp(hay.as.s+i,needle.as.s,nn)==0)return sv_bool(true);return sv_bool(false);}
    if(hay.tag==SV_MAP)return sv_bool(sv_map_find(hay.as.map,needle)>=0);
    sv_fail("in requires list/string/map haystack");return sv_bool(false);
}
static SlugValue sv_iv(SlugValue needle,SlugValue hay){if(hay.tag!=SV_MAP)sv_fail("iv requires map");for(size_t i=0;i<hay.as.map->len;i++)if(sv_equal(needle,hay.as.map->vals[i]))return sv_bool(true);return sv_bool(false);}
static SlugValue sv_ln(SlugValue v){return sv_int(sv_len_i(v));}
static SlugValue sv_sl(SlugValue v){if(v.tag!=SV_LIST)sv_fail("sl requires list");if(v.as.list->frozen)sv_fail("cannot sort frozen list");for(size_t i=1;i<v.as.list->len;i++){SlugValue x=v.as.list->items[i];size_t j=i;while(j>0&&sv_compare(v.as.list->items[j-1],x)>0){v.as.list->items[j]=v.as.list->items[j-1];j--;}v.as.list->items[j]=x;}return v;}
static SlugValue sv_iter_at(SlugValue v,int64_t i){if(v.tag==SV_MAP){if(i<0||i>=(int64_t)v.as.map->len)sv_fail("iteration index out of range");return v.as.map->keys[i];}return sv_index(v,sv_int(i));}

static SlugValue sv_co(SlugValue a){SvBuf b;sb_init(&b);sv_format_into(&b,a);if(b.n)fwrite(b.p,1,b.n,stdout);fputc('\n',stdout);fflush(stdout);free(b.p);return sv_null();}
static SlugValue sv_ci(SlugValue prompt){if(prompt.tag!=SV_STRING)sv_fail_kind("type","ci prompt must be string");size_t pn=sv_string_bytes(prompt.as.s);if(pn)fwrite(prompt.as.s,1,pn,stdout);fflush(stdout);SvBuf b;sb_init(&b);int ch;bool any=false;while((ch=fgetc(stdin))!=EOF){any=true;if(ch=='\n')break;sb_ch(&b,(char)ch);}if(!any&&ch==EOF){free(b.p);return sv_null();}if(b.n&&b.p[b.n-1]=='\r'){b.n--;b.p[b.n]=0;}SlugValue out=sv_string_n((const unsigned char*)b.p,b.n);free(b.p);return out;}

static SlugValue sv_by(SlugValue v){
    if(v.tag==SV_BYTES)return v;
    if(v.tag==SV_STRING)return sv_bytes((const unsigned char*)(v.as.s?v.as.s:""),sv_string_bytes(v.as.s));
    if(v.tag==SV_LIST){size_t n=v.as.list->len;unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;for(size_t i=0;i<n;i++){uint64_t x=sv_u64_numeric(v.as.list->items[i]);if(x>255)sv_fail_kind("range","byte value out of range");p[i]=(unsigned char)x;}SlugValue out=sv_bytes(p,n);free(p);return out;}
    sv_fail_kind("type","by requires string/list/bytes");return sv_null();
}

/* Native capability foundation. */
static const char *sv_require_string(SlugValue v,const char *what){if(v.tag!=SV_STRING)sv_fail_kind("type",what);if(sv_string_has_nul(v))sv_fail_kind("encoding","embedded NUL is not valid in terminated host text");return v.as.s?v.as.s:"";}

static bool sv_utf8_valid(const unsigned char *s,size_t n){
    size_t i=0;while(i<n){unsigned char c=s[i++];if(c<0x80)continue;unsigned need;uint32_t cp;
        if((c&0xE0)==0xC0){need=1;cp=c&0x1F;if(cp<2)return false;}
        else if((c&0xF0)==0xE0){need=2;cp=c&0x0F;}
        else if((c&0xF8)==0xF0){need=3;cp=c&7;if(cp>4)return false;}
        else return false;if(i+need>n)return false;
        for(unsigned k=0;k<need;k++){unsigned char d=s[i++];if((d&0xC0)!=0x80)return false;cp=(cp<<6)|(d&0x3F);}
        if((need==2&&cp<0x800)||(need==3&&cp<0x10000)||cp>0x10FFFF||(cp>=0xD800&&cp<=0xDFFF))return false;
    }return true;
}
#ifdef _WIN32
static wchar_t *sv_widen(const char *s){int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,NULL,0);if(!n)sv_fail("invalid UTF-8 path");wchar_t *w=(wchar_t*)sv_xmalloc(sizeof(wchar_t)*(size_t)n);if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,w,n)){free(w);sv_fail("path conversion failed");}return w;}
static char *sv_narrow(const wchar_t *w){int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,w,-1,NULL,0,NULL,NULL);if(!n)sv_fail("path conversion failed");char *s=(char*)sv_xmalloc((size_t)n);if(!WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,w,-1,s,n,NULL,NULL)){free(s);sv_fail("path conversion failed");}return s;}
static FILE *sv_fopen_utf8(const char *path,const wchar_t *mode){wchar_t *w=sv_widen(path);FILE *f=_wfopen(w,mode);free(w);return f;}
#else
static FILE *sv_fopen_utf8(const char *path,const char *mode){return fopen(path,mode);}
#endif
static SlugValue sv_read_file_bytes(const char *path){
#ifdef _WIN32
    FILE *f=sv_fopen_utf8(path,L"rb");
#else
    FILE *f=sv_fopen_utf8(path,"rb");
#endif
    if(!f)sv_fail("cannot open file for reading");size_t n=0,cap=8192;unsigned char *p=(unsigned char*)sv_xmalloc(cap);
    for(;;){if(n==cap){if(cap>SIZE_MAX/2){fclose(f);free(p);sv_fail("file too large");}cap*=2;p=(unsigned char*)sv_xrealloc(p,cap);}size_t got=fread(p+n,1,cap-n,f);n+=got;if(got==0){if(ferror(f)){fclose(f);free(p);sv_fail("file read failed");}break;}}
    fclose(f);SlugValue v=sv_bytes(p,n);free(p);return v;
}
static SlugValue sv_read_file_text(const char *path){SlugValue b=sv_read_file_bytes(path);if(!sv_utf8_valid(b.as.bytes->data,b.as.bytes->len))sv_fail_kind("encoding","text file is not valid UTF-8");return sv_string_n(b.as.bytes->data,b.as.bytes->len);}
static size_t sv_write_payload(FILE *f,SlugValue data){const unsigned char *p;size_t n;if(data.tag==SV_BYTES){p=data.as.bytes->data;n=data.as.bytes->len;}else if(data.tag==SV_STRING){p=(const unsigned char*)(data.as.s?data.as.s:"");n=sv_string_bytes(data.as.s);}else sv_fail("file write requires string/bytes");if(n&&fwrite(p,1,n,f)!=n)sv_fail("file write failed");if(fflush(f)!=0)sv_fail("file flush failed");return n;}
static SlugValue sv_write_file(const char *path,SlugValue data,bool append){
#ifdef _WIN32
    FILE *f=sv_fopen_utf8(path,append?L"ab":L"wb");
#else
    FILE *f=sv_fopen_utf8(path,append?"ab":"wb");
#endif
    if(!f)sv_fail("cannot open file for writing");size_t n=sv_write_payload(f,data);if(fclose(f)!=0)sv_fail("file close failed");return sv_int((int64_t)n);
}
static SlugValue sv_file_exists(const char *path){
#ifdef _WIN32
    wchar_t *w=sv_widen(path);DWORD a=GetFileAttributesW(w);free(w);return sv_bool(a!=INVALID_FILE_ATTRIBUTES);
#else
    struct stat st;return sv_bool(stat(path,&st)==0);
#endif
}
static SlugValue sv_file_meta(const char *path){
    uint64_t size=0;double mtime=0;bool isdir=false,isfile=false;
#ifdef _WIN32
    wchar_t *w=sv_widen(path);struct _stat64 st;if(_wstat64(w,&st)!=0){free(w);sv_fail("file stat failed");}free(w);size=(uint64_t)st.st_size;mtime=(double)st.st_mtime;isdir=(st.st_mode&_S_IFDIR)!=0;isfile=(st.st_mode&_S_IFREG)!=0;
#else
    struct stat st;if(stat(path,&st)!=0)sv_fail("file stat failed");size=(uint64_t)st.st_size;mtime=(double)st.st_mtime;isdir=S_ISDIR(st.st_mode);isfile=S_ISREG(st.st_mode);
#endif
    SlugMap *m=sv_map_new_raw(false,4);sv_map_put_raw(m,sv_string("size"),sv_uint(size));sv_map_put_raw(m,sv_string("mtime"),sv_float(mtime));sv_map_put_raw(m,sv_string("dir"),sv_bool(isdir));sv_map_put_raw(m,sv_string("file"),sv_bool(isfile));return sv_map_value(m);
}
static SlugValue sv_dir_list(const char *path){SlugList *l=sv_list_new_raw(false,0);
#ifdef _WIN32
    wchar_t *w=sv_widen(path);size_t n=wcslen(w);wchar_t *pat=(wchar_t*)sv_xmalloc(sizeof(wchar_t)*(n+3));wcscpy(pat,w);if(n&&w[n-1]!=L'\\'&&w[n-1]!=L'/')pat[n++]=L'\\';pat[n++]=L'*';pat[n]=0;WIN32_FIND_DATAW d;HANDLE h=FindFirstFileW(pat,&d);free(pat);free(w);if(h==INVALID_HANDLE_VALUE){DWORD e=GetLastError();if(e==ERROR_FILE_NOT_FOUND)return sv_list_value(l);sv_fail("directory listing failed");}do{if(wcscmp(d.cFileName,L".")&&wcscmp(d.cFileName,L"..")){char *x=sv_narrow(d.cFileName);sv_list_append(l,sv_string(x));free(x);}}while(FindNextFileW(h,&d));FindClose(h);
#else
    DIR *d=opendir(path);if(!d)sv_fail("directory listing failed");struct dirent *e;while((e=readdir(d))){if(strcmp(e->d_name,".")&&strcmp(e->d_name,".."))sv_list_append(l,sv_string(e->d_name));}closedir(d);
#endif
    SlugValue v=sv_list_value(l);return sv_sl(v);
}
static SlugValue sv_make_dir(const char *path){
#ifdef _WIN32
    wchar_t *w=sv_widen(path);if(CreateDirectoryW(w,NULL)){free(w);return sv_bool(true);}DWORD e=GetLastError();if(e==ERROR_ALREADY_EXISTS){DWORD a=GetFileAttributesW(w);free(w);if(a!=INVALID_FILE_ATTRIBUTES&&(a&FILE_ATTRIBUTE_DIRECTORY))return sv_bool(false);}free(w);sv_fail("mkdir failed");
#else
    if(mkdir(path,0777)==0)return sv_bool(true);if(errno==EEXIST){struct stat st;if(stat(path,&st)==0&&S_ISDIR(st.st_mode))return sv_bool(false);}sv_fail("mkdir failed");
#endif
    return sv_bool(false);
}
static SlugValue sv_remove_path(const char *path){
#ifdef _WIN32
    wchar_t *w=sv_widen(path);DWORD a=GetFileAttributesW(w);if(a==INVALID_FILE_ATTRIBUTES){DWORD e=GetLastError();free(w);if(e==ERROR_FILE_NOT_FOUND||e==ERROR_PATH_NOT_FOUND)return sv_bool(false);sv_fail("remove stat failed");}BOOL ok=(a&FILE_ATTRIBUTE_DIRECTORY)?RemoveDirectoryW(w):DeleteFileW(w);free(w);if(!ok)sv_fail("remove failed");return sv_bool(true);
#else
    struct stat st;if(lstat(path,&st)!=0){if(errno==ENOENT)return sv_bool(false);sv_fail("remove stat failed");}int rc=S_ISDIR(st.st_mode)?rmdir(path):unlink(path);if(rc!=0)sv_fail("remove failed");return sv_bool(true);
#endif
}
static SlugValue sv_move_path(const char *a,const char *b){
#ifdef _WIN32
    wchar_t *wa=sv_widen(a),*wb=sv_widen(b);BOOL ok=MoveFileExW(wa,wb,MOVEFILE_REPLACE_EXISTING);free(wa);free(wb);if(!ok)sv_fail("rename failed");
#else
    if(rename(a,b)!=0)sv_fail("rename failed");
#endif
    return sv_null();
}
static SlugValue sv_args_value(void){
#ifdef _WIN32
    int argcw=0;LPWSTR *argvw=CommandLineToArgvW(GetCommandLineW(),&argcw);if(!argvw)sv_fail("argument decoding failed");size_t n=argcw>1?(size_t)(argcw-1):0;SlugList *l=sv_list_new_raw(false,n);for(size_t i=0;i<n;i++){char *x=sv_narrow(argvw[i+1]);l->items[i]=sv_string(x);free(x);}LocalFree(argvw);return sv_list_value(l);
#else
    size_t n=sv_argc>1?(size_t)(sv_argc-1):0;SlugList *l=sv_list_new_raw(false,n);for(size_t i=0;i<n;i++)l->items[i]=sv_string(sv_argv[i+1]?sv_argv[i+1]:"");return sv_list_value(l);
#endif
}
static SlugValue sv_cli_executable_path_value(void){
#ifdef _WIN32
    DWORD cap=512;for(;;){wchar_t *w=(wchar_t*)sv_xmalloc(sizeof(wchar_t)*(size_t)cap);DWORD n=GetModuleFileNameW(NULL,w,cap);if(n>0&&n<cap-1){char *x=sv_narrow(w);free(w);return sv_string_owned(x);}free(w);if(!n)sv_fail("executable path query failed");if(cap>32768)sv_fail("executable path too long");cap*=2;}
#else
#ifdef __linux__
    size_t cap=512;for(;;){char *p=(char*)sv_xmalloc(cap);ssize_t n=readlink("/proc/self/exe",p,cap-1);if(n<0){free(p);break;}if((size_t)n<cap-1){p[n]=0;return sv_string_owned(p);}free(p);cap*=2;if(cap>(1u<<20))break;}
#endif
    if(sv_argc>0&&sv_argv&&sv_argv[0])return sv_string(sv_argv[0]);
    return sv_string("");
#endif
}
static SlugValue sv_cli_stderr_value(SlugValue v){const char *s=sv_require_string(v,"internal cli stderr requires string");size_t n=sv_string_bytes(v.as.s);if(n)fwrite(s,1,n,stderr);fputc('\n',stderr);fflush(stderr);return sv_null();}
static SlugValue sv_cli_stdout_value(SlugValue v){const char *s=sv_require_string(v,"internal cli stdout requires string");size_t n=sv_string_bytes(v.as.s);if(n)fwrite(s,1,n,stdout);fflush(stdout);return sv_null();}
static SlugValue sv_cli_exit_value(SlugValue v){int64_t c=sv_int_num(v);if(c<0||c>255)sv_fail_kind("range","internal cli exit status out of range");fflush(NULL);sv_runtime_shutdown();exit((int)c);return sv_null();}
static SlugValue sv_env_value(const char *name){
#ifdef _WIN32
    wchar_t *wn=sv_widen(name);wchar_t *wv=_wgetenv(wn);free(wn);if(!wv)return sv_null();char *x=sv_narrow(wv);SlugValue out=sv_string(x);free(x);return out;
#else
    const char *v=getenv(name);return v?sv_string(v):sv_null();
#endif
}
static SlugValue sv_cwd_value(void){
#ifdef _WIN32
    DWORD n=GetCurrentDirectoryW(0,NULL);if(!n)sv_fail("cwd failed");wchar_t *w=(wchar_t*)sv_xmalloc(sizeof(wchar_t)*(size_t)n);if(!GetCurrentDirectoryW(n,w)){free(w);sv_fail("cwd failed");}char *x=sv_narrow(w);free(w);return sv_string_owned(x);
#else
    size_t cap=256;for(;;){char *p=(char*)sv_xmalloc(cap);if(getcwd(p,cap))return sv_string_owned(p);free(p);if(errno!=ERANGE)sv_fail("cwd failed");cap*=2;}
#endif
}
static SlugValue sv_platform_value(void){SlugMap *m=sv_map_new_raw(false,2);
#ifdef _WIN32
    sv_map_put_raw(m,sv_string("os"),sv_string("windows"));sv_map_put_raw(m,sv_string("sep"),sv_string("\\"));
#else
    sv_map_put_raw(m,sv_string("os"),sv_string("posix"));sv_map_put_raw(m,sv_string("sep"),sv_string("/"));
#endif
    return sv_map_value(m);
}
static double sv_wall_seconds(void){
#ifdef _WIN32
    FILETIME ft;GetSystemTimeAsFileTime(&ft);ULARGE_INTEGER u;u.LowPart=ft.dwLowDateTime;u.HighPart=ft.dwHighDateTime;return ((double)u.QuadPart/10000000.0)-11644473600.0;
#else
    struct timespec ts;if(timespec_get(&ts,TIME_UTC)!=TIME_UTC)sv_fail("wall clock failed");return (double)ts.tv_sec+(double)ts.tv_nsec/1e9;
#endif
}
static double sv_mono_seconds(void){
#ifdef _WIN32
    LARGE_INTEGER f,c;if(!QueryPerformanceFrequency(&f)||!QueryPerformanceCounter(&c))sv_fail("monotonic clock failed");return (double)c.QuadPart/(double)f.QuadPart;
#else
    struct timespec ts;if(clock_gettime(CLOCK_MONOTONIC,&ts)!=0)sv_fail("monotonic clock failed");return (double)ts.tv_sec+(double)ts.tv_nsec/1e9;
#endif
}
static SlugValue sv_wait_seconds(SlugValue v){double x=sv_num(v);if(x<0)sv_fail("negative sleep duration");
#ifdef _WIN32
    double ms=x*1000.0;if(ms>(double)UINT32_MAX)sv_fail("sleep duration too large");Sleep((DWORD)(ms+0.5));
#else
    struct timespec req={(time_t)x,(long)((x-(double)(time_t)x)*1e9)};while(nanosleep(&req,&req)!=0)if(errno!=EINTR)sv_fail("sleep failed");
#endif
    return sv_null();
}
static SlugValue sv_entropy_value(SlugValue nv){int64_t ni=sv_int_num(nv);if(ni<0||ni>16777216)sv_fail("entropy length out of range");size_t n=(size_t)ni;unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;
#ifdef _WIN32
    size_t i=0;while(i<n){unsigned int x;if(rand_s(&x)!=0){free(p);sv_fail("system entropy failed");}for(unsigned k=0;k<sizeof(x)&&i<n;k++,i++)p[i]=(unsigned char)(x>>(k*8));}
#else
    FILE *f=fopen("/dev/urandom","rb");if(!f){free(p);sv_fail("system entropy unavailable");}if(n&&fread(p,1,n,f)!=n){fclose(f);free(p);sv_fail("system entropy failed");}fclose(f);
#endif
    SlugValue out=sv_bytes(p,n);free(p);return out;
}

static SlugFile *sv_require_file(SlugValue v){if(v.tag!=SV_FILE||!v.as.file||v.as.file->closed||!v.as.file->f)sv_fail("open file handle required");return v.as.file;}
static SlugValue sv_file_open_value(SlugValue pathv,SlugValue modev){const char *path=sv_require_string(pathv,"fo requires path string");const char *mode=sv_require_string(modev,"fo requires mode string");
#ifdef _WIN32
    const wchar_t *wm=NULL;if(strcmp(mode,"r")==0)wm=L"rb";else if(strcmp(mode,"w")==0)wm=L"wb";else if(strcmp(mode,"a")==0)wm=L"ab";else if(strcmp(mode,"r+")==0)wm=L"r+b";else if(strcmp(mode,"w+")==0)wm=L"w+b";else if(strcmp(mode,"a+")==0)wm=L"a+b";else sv_fail("invalid file mode");FILE *fp=sv_fopen_utf8(path,wm);
#else
    const char *cm=NULL;if(strcmp(mode,"r")==0)cm="rb";else if(strcmp(mode,"w")==0)cm="wb";else if(strcmp(mode,"a")==0)cm="ab";else if(strcmp(mode,"r+")==0)cm="r+b";else if(strcmp(mode,"w+")==0)cm="w+b";else if(strcmp(mode,"a+")==0)cm="a+b";else sv_fail("invalid file mode");FILE *fp=sv_fopen_utf8(path,cm);
#endif
    if(!fp)sv_fail("cannot open file handle");return sv_file_value(fp);
}
static SlugValue sv_file_handle_read(SlugValue fv,SlugValue nv){SlugFile *f=sv_require_file(fv);int64_t ni=sv_int_num(nv);if(ni<0||ni>16777216)sv_fail("file read length out of range");size_t n=(size_t)ni;unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;size_t got=n?fread(p,1,n,f->f):0;if(got<n&&ferror(f->f)){free(p);sv_fail("file handle read failed");}SlugValue out=sv_bytes(p,got);free(p);return out;}
static SlugValue sv_file_handle_write(SlugValue fv,SlugValue data){SlugFile *f=sv_require_file(fv);const unsigned char *p;size_t n;if(data.tag==SV_BYTES){p=data.as.bytes->data;n=data.as.bytes->len;}else if(data.tag==SV_STRING){p=(const unsigned char*)(data.as.s?data.as.s:"");n=sv_string_bytes(data.as.s);}else sv_fail("file handle write requires string/bytes");if(n&&fwrite(p,1,n,f->f)!=n)sv_fail("file handle write failed");if(n>(size_t)INT64_MAX)sv_fail("file handle write count overflow");return sv_int((int64_t)n);}
static int64_t sv_file_tell_raw(SlugFile *f){
#ifdef _WIN32
    __int64 p=_ftelli64(f->f);if(p<0)sv_fail("file tell failed");return (int64_t)p;
#else
    off_t p=ftello(f->f);if(p<(off_t)0||p>(off_t)INT64_MAX)sv_fail("file tell failed");return (int64_t)p;
#endif
}
static SlugValue sv_file_seek_value(SlugValue fv,SlugValue offv,SlugValue whencev){SlugFile *f=sv_require_file(fv);int64_t off=sv_int_num(offv),w=sv_int_num(whencev);int wh;if(w==0)wh=SEEK_SET;else if(w==1)wh=SEEK_CUR;else if(w==2)wh=SEEK_END;else sv_fail("file seek origin out of range");
#ifdef _WIN32
    if(_fseeki64(f->f,(__int64)off,wh)!=0)sv_fail("file seek failed");
#else
    if(fseeko(f->f,(off_t)off,wh)!=0)sv_fail("file seek failed");
#endif
    return sv_int(sv_file_tell_raw(f));}
static SlugValue sv_file_tell_value(SlugValue fv){return sv_int(sv_file_tell_raw(sv_require_file(fv)));}
static SlugValue sv_file_flush_value(SlugValue fv){SlugFile *f=sv_require_file(fv);if(fflush(f->f)!=0)sv_fail("file flush failed");return sv_null();}
static SlugValue sv_file_close_value(SlugValue fv){if(fv.tag!=SV_FILE||!fv.as.file)sv_fail("file handle required");sv_file_close_raw(fv.as.file);return sv_null();}

static SlugValue sv_process_run(SlugValue av){if(av.tag!=SV_LIST||!av.as.list->len)sv_fail("pc requires non-empty argv list");size_t n=av.as.list->len;for(size_t i=0;i<n;i++)if(av.as.list->items[i].tag!=SV_STRING)sv_fail("pc argv entries must be strings");
#ifdef _WIN32
    SvBuf cmd;sb_init(&cmd);for(size_t ai=0;ai<n;ai++){const char *a=av.as.list->items[ai].as.s?av.as.list->items[ai].as.s:"";if(ai)sb_ch(&cmd,' ');sb_ch(&cmd,'\"');const char *p=a;for(;;){size_t bs=0;while(*p=='\\'){bs++;p++;}if(*p=='\"'){for(size_t k=0;k<bs*2+1;k++)sb_ch(&cmd,'\\');sb_ch(&cmd,'\"');p++;continue;}if(*p=='\0'){for(size_t k=0;k<bs*2;k++)sb_ch(&cmd,'\\');break;}for(size_t k=0;k<bs;k++)sb_ch(&cmd,'\\');sb_ch(&cmd,*p++);}sb_ch(&cmd,'\"');}wchar_t *w=sv_widen(cmd.p);free(cmd.p);STARTUPINFOW si;PROCESS_INFORMATION pi;memset(&si,0,sizeof(si));memset(&pi,0,sizeof(pi));si.cb=sizeof(si);BOOL ok=CreateProcessW(NULL,w,NULL,NULL,FALSE,0,NULL,NULL,&si,&pi);free(w);if(!ok)sv_fail("process spawn failed");WaitForSingleObject(pi.hProcess,INFINITE);DWORD code=0;if(!GetExitCodeProcess(pi.hProcess,&code)){CloseHandle(pi.hThread);CloseHandle(pi.hProcess);sv_fail("process wait failed");}CloseHandle(pi.hThread);CloseHandle(pi.hProcess);return sv_int((int64_t)code);
#else
    char **args=(char**)sv_xmalloc(sizeof(char*)*(n+1));for(size_t i=0;i<n;i++)args[i]=av.as.list->items[i].as.s;args[n]=NULL;pid_t pid=fork();if(pid<0){free(args);sv_fail("process spawn failed");}if(pid==0){execvp(args[0],args);_exit(127);}free(args);int status=0;while(waitpid(pid,&status,0)<0){if(errno==EINTR)continue;sv_fail("process wait failed");}if(WIFEXITED(status))return sv_int(WEXITSTATUS(status));if(WIFSIGNALED(status))return sv_int(128+WTERMSIG(status));sv_fail("process ended without status");
#endif
    return sv_int(0);
}

static SlugSocket *sv_require_socket(SlugValue v){if(v.tag!=SV_SOCKET||!v.as.sock||v.as.sock->closed)sv_fail("open socket required");return v.as.sock;}
static int sv_socket_error(void){
#ifdef _WIN32
return WSAGetLastError();
#else
return errno;
#endif
}
static SlugValue sv_socket_new_tcp(void){SvSocketHandle h=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);if(h==SV_BAD_SOCKET)sv_fail("socket creation failed");return sv_socket_value(h);}
static void sv_socket_addr(const char *host,uint16_t port,bool passive,struct sockaddr_storage *out,SvSockLen *outlen){char service[16];snprintf(service,sizeof(service),"%u",(unsigned)port);struct addrinfo hints;memset(&hints,0,sizeof(hints));hints.ai_family=AF_INET;hints.ai_socktype=SOCK_STREAM;hints.ai_protocol=IPPROTO_TCP;if(passive)hints.ai_flags=AI_PASSIVE;struct addrinfo *res=NULL;int rc=getaddrinfo((host&&host[0])?host:NULL,service,&hints,&res);if(rc!=0||!res)sv_fail("socket address resolution failed");if(res->ai_addrlen>sizeof(*out)){freeaddrinfo(res);sv_fail("socket address too large");}memcpy(out,res->ai_addr,res->ai_addrlen);*outlen=(SvSockLen)res->ai_addrlen;freeaddrinfo(res);}
static uint16_t sv_port(SlugValue v){uint64_t p=sv_u64_numeric(v);if(p>65535)sv_fail("socket port out of range");return (uint16_t)p;}
static SlugValue sv_socket_connect(SlugValue sv,SlugValue hostv,SlugValue portv){SlugSocket *s=sv_require_socket(sv);struct sockaddr_storage a;SvSockLen n;sv_socket_addr(sv_require_string(hostv,"socket host must be string"),sv_port(portv),false,&a,&n);if(connect(s->h,(struct sockaddr*)&a,n)!=0)sv_fail("socket connect failed");return sv_null();}
static SlugValue sv_socket_bind(SlugValue sv,SlugValue hostv,SlugValue portv){SlugSocket *s=sv_require_socket(sv);int one=1;setsockopt(s->h,SOL_SOCKET,SO_REUSEADDR,(const char*)&one,sizeof(one));struct sockaddr_storage a;SvSockLen n;sv_socket_addr(sv_require_string(hostv,"socket host must be string"),sv_port(portv),true,&a,&n);if(bind(s->h,(struct sockaddr*)&a,n)!=0)sv_fail("socket bind failed");return sv_null();}
static SlugValue sv_socket_listen(SlugValue sv,SlugValue backlogv){SlugSocket *s=sv_require_socket(sv);int64_t b=sv_int_num(backlogv);if(b<0||b>65535)sv_fail("socket backlog out of range");if(listen(s->h,(int)b)!=0)sv_fail("socket listen failed");return sv_null();}
static SlugValue sv_socket_accept(SlugValue sv){SlugSocket *s=sv_require_socket(sv);SvSocketHandle h=accept(s->h,NULL,NULL);if(h==SV_BAD_SOCKET)sv_fail("socket accept failed");return sv_socket_value(h);}
static SlugValue sv_socket_send(SlugValue sv,SlugValue data){SlugSocket *s=sv_require_socket(sv);const unsigned char *p;size_t n;if(data.tag==SV_BYTES){p=data.as.bytes->data;n=data.as.bytes->len;}else if(data.tag==SV_STRING){p=(const unsigned char*)(data.as.s?data.as.s:"");n=sv_string_bytes(data.as.s);}else sv_fail("socket send requires string/bytes");size_t sent=0;while(sent<n){size_t left=n-sent;int chunk=left>INT_MAX?INT_MAX:(int)left;
#ifdef _WIN32
int r=send(s->h,(const char*)p+sent,chunk,0);
#else
ssize_t r=send(s->h,p+sent,(size_t)chunk,0);
#endif
if(r<=0)sv_fail("socket send failed");sent+=(size_t)r;}if(sent>(size_t)INT64_MAX)sv_fail("socket send count overflow");return sv_int((int64_t)sent);}
static SlugValue sv_socket_recv(SlugValue sv,SlugValue maxv){SlugSocket *s=sv_require_socket(sv);int64_t m=sv_int_num(maxv);if(m<0||m>16777216)sv_fail("socket receive length out of range");size_t n=(size_t)m;unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;
#ifdef _WIN32
int r=n?recv(s->h,(char*)p,(int)n,0):0;if(r==SOCKET_ERROR){free(p);sv_fail("socket receive failed");}
#else
ssize_t r=n?recv(s->h,p,n,0):0;if(r<0){free(p);sv_fail("socket receive failed");}
#endif
SlugValue out=sv_bytes(p,(size_t)r);free(p);return out;}
static SlugValue sv_socket_close(SlugValue sv){if(sv.tag!=SV_SOCKET||!sv.as.sock)sv_fail("socket required");sv_socket_close_raw(sv.as.sock);return sv_null();}
static SlugValue sv_socket_port(SlugValue sv){SlugSocket *s=sv_require_socket(sv);struct sockaddr_in a;SvSockLen n=(SvSockLen)sizeof(a);if(getsockname(s->h,(struct sockaddr*)&a,&n)!=0)sv_fail("socket port query failed");return sv_int((int64_t)ntohs(a.sin_port));}

/* v0.1.7 low-level surface / host-I/O bones. */
static SlugSurface *sv_require_surface(SlugValue v){if(v.tag!=SV_SURFACE||!v.as.surface)sv_fail("surface required");return v.as.surface;}
static SlugValue sv_surface_new_value(SlugValue wv,SlugValue hv){int64_t w=sv_int_num(wv),h=sv_int_num(hv);if(w<=0||h<=0||w>32768||h>32768)sv_fail("surface dimensions out of range");if((uint64_t)w*(uint64_t)h>SIZE_MAX/4)sv_fail("surface size overflow");SlugSurface *s=(SlugSurface*)sv_heap_alloc(sizeof(SlugSurface),SH_SURFACE);s->width=(int)w;s->height=(int)h;s->len=(size_t)w*(size_t)h*4;s->pixels=(unsigned char*)sv_xmalloc(s->len);memset(s->pixels,0,s->len);return sv_surface_value(s);}
static uint32_t sv_rgba(SlugValue v){uint64_t x=sv_u64_numeric(v);if(x>UINT32_MAX)sv_fail("RGBA color out of range");return (uint32_t)x;}
static void sv_surface_pixel_raw(SlugSurface *s,int64_t x,int64_t y,uint32_t c){if(x<0||y<0||x>=s->width||y>=s->height)return;size_t i=((size_t)y*(size_t)s->width+(size_t)x)*4;s->pixels[i]=(unsigned char)(c>>24);s->pixels[i+1]=(unsigned char)(c>>16);s->pixels[i+2]=(unsigned char)(c>>8);s->pixels[i+3]=(unsigned char)c;}
static SlugValue sv_surface_pixel(SlugValue sv,SlugValue xv,SlugValue yv,SlugValue cv){SlugSurface *s=sv_require_surface(sv);int64_t x=sv_int_num(xv),y=sv_int_num(yv);if(x<0||y<0||x>=s->width||y>=s->height)sv_fail("pixel coordinate out of range");sv_surface_pixel_raw(s,x,y,sv_rgba(cv));return sv_null();}
static SlugValue sv_surface_rect(SlugValue sv,SlugValue xv,SlugValue yv,SlugValue wv,SlugValue hv,SlugValue cv){SlugSurface *s=sv_require_surface(sv);int64_t x=sv_int_num(xv),y=sv_int_num(yv),w=sv_int_num(wv),h=sv_int_num(hv);if(w<0||h<0)sv_fail("rectangle size out of range");uint32_t c=sv_rgba(cv);for(int64_t yy=0;yy<h;yy++)for(int64_t xx=0;xx<w;xx++)sv_surface_pixel_raw(s,x+xx,y+yy,c);return sv_null();}
static SlugValue sv_surface_line(SlugValue sv,SlugValue x0v,SlugValue y0v,SlugValue x1v,SlugValue y1v,SlugValue cv){SlugSurface *s=sv_require_surface(sv);int64_t x0=sv_int_num(x0v),y0=sv_int_num(y0v),x1=sv_int_num(x1v),y1=sv_int_num(y1v);uint32_t c=sv_rgba(cv);int64_t dx=llabs(x1-x0),sx=x0<x1?1:-1,dy=-llabs(y1-y0),sy=y0<y1?1:-1,err=dx+dy;for(;;){sv_surface_pixel_raw(s,x0,y0,c);if(x0==x1&&y0==y1)break;int64_t e2=2*err;if(e2>=dy){err+=dy;x0+=sx;}if(e2<=dx){err+=dx;y0+=sy;}}return sv_null();}
static SlugValue sv_surface_bytes(SlugValue sv){SlugSurface *s=sv_require_surface(sv);return sv_bytes(s->pixels,s->len);}

static SlugWindow *sv_require_window(SlugValue v){if(v.tag!=SV_WINDOW||!v.as.window||v.as.window->closed)sv_fail("open window required");return v.as.window;}
#ifdef _WIN32
static LRESULT CALLBACK sv_window_proc(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp){(void)wp;(void)lp;if(msg==WM_CLOSE)return 0;return DefWindowProcW(hwnd,msg,wp,lp);}
static void sv_window_class(void){static bool done=false;if(done)return;WNDCLASSW wc;memset(&wc,0,sizeof(wc));wc.lpfnWndProc=sv_window_proc;wc.hInstance=GetModuleHandleW(NULL);wc.lpszClassName=L"SLUG_v017_Window";wc.hCursor=LoadCursor(NULL,IDC_ARROW);if(!RegisterClassW(&wc)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)sv_fail("window class registration failed");done=true;}
#endif
static SlugValue sv_window_new_value(SlugValue wv,SlugValue hv,SlugValue titlev){int64_t w=sv_int_num(wv),h=sv_int_num(hv);const char *title=sv_require_string(titlev,"window title must be string");if(w<=0||h<=0||w>32768||h>32768)sv_fail("window dimensions out of range");
#ifndef _WIN32
(void)title;sv_fail("window capability unavailable on this platform");return sv_null();
#else
sv_window_class();wchar_t *wt=sv_widen(title);RECT r={0,0,(LONG)w,(LONG)h};AdjustWindowRect(&r,WS_OVERLAPPEDWINDOW,FALSE);HWND hwnd=CreateWindowExW(0,L"SLUG_v017_Window",wt,WS_OVERLAPPEDWINDOW,CW_USEDEFAULT,CW_USEDEFAULT,r.right-r.left,r.bottom-r.top,NULL,NULL,GetModuleHandleW(NULL),NULL);free(wt);if(!hwnd)sv_fail("window creation failed");SlugWindow *x=(SlugWindow*)sv_heap_alloc(sizeof(SlugWindow),SH_WINDOW);x->closed=false;x->width=(int)w;x->height=(int)h;x->hwnd=hwnd;ShowWindow(hwnd,SW_SHOW);UpdateWindow(hwnd);return sv_window_value(x);
#endif
}
static SlugValue sv_window_present(SlugValue wv,SlugValue sv){SlugWindow *w=sv_require_window(wv);SlugSurface *s=sv_require_surface(sv);
#ifndef _WIN32
(void)w;(void)s;sv_fail("window capability unavailable on this platform");return sv_null();
#else
size_t n=s->len;unsigned char *bgra=(unsigned char*)sv_xmalloc(n);for(size_t i=0;i<n;i+=4){bgra[i]=s->pixels[i+2];bgra[i+1]=s->pixels[i+1];bgra[i+2]=s->pixels[i];bgra[i+3]=s->pixels[i+3];}BITMAPINFO bi;memset(&bi,0,sizeof(bi));bi.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);bi.bmiHeader.biWidth=s->width;bi.bmiHeader.biHeight=-s->height;bi.bmiHeader.biPlanes=1;bi.bmiHeader.biBitCount=32;bi.bmiHeader.biCompression=BI_RGB;HDC dc=GetDC(w->hwnd);if(!dc){free(bgra);sv_fail("window presentation failed");}int ok=StretchDIBits(dc,0,0,w->width,w->height,0,0,s->width,s->height,bgra,&bi,DIB_RGB_COLORS,SRCCOPY);ReleaseDC(w->hwnd,dc);free(bgra);if(ok==GDI_ERROR)sv_fail("window presentation failed");return sv_null();
#endif
}
static SlugValue sv_event_map(const char *type){SlugMap *m=sv_map_new_raw(false,4);sv_map_put_raw(m,sv_string("type"),sv_string(type));return sv_map_value(m);}
static void sv_event_put(SlugValue mv,const char *key,SlugValue value){sv_map_put_raw(mv.as.map,sv_string(key),value);}
static SlugValue sv_window_poll(SlugValue wv){SlugWindow *w=sv_require_window(wv);
#ifndef _WIN32
(void)w;sv_fail("window capability unavailable on this platform");return sv_null();
#else
MSG m;while(PeekMessageW(&m,w->hwnd,0,0,PM_REMOVE)){SlugValue e=sv_null();switch(m.message){case WM_CLOSE:e=sv_event_map("close");break;case WM_SIZE:e=sv_event_map("resize");w->width=(int)(uint16_t)LOWORD(m.lParam);w->height=(int)(uint16_t)HIWORD(m.lParam);sv_event_put(e,"width",sv_int(w->width));sv_event_put(e,"height",sv_int(w->height));break;case WM_KEYDOWN:case WM_SYSKEYDOWN:case WM_KEYUP:case WM_SYSKEYUP:e=sv_event_map("key");sv_event_put(e,"down",sv_bool(m.message==WM_KEYDOWN||m.message==WM_SYSKEYDOWN));sv_event_put(e,"code",sv_int((int64_t)m.wParam));break;case WM_MOUSEMOVE:e=sv_event_map("mouse");sv_event_put(e,"x",sv_int((int16_t)LOWORD(m.lParam)));sv_event_put(e,"y",sv_int((int16_t)HIWORD(m.lParam)));break;case WM_LBUTTONDOWN:case WM_LBUTTONUP:case WM_RBUTTONDOWN:case WM_RBUTTONUP:case WM_MBUTTONDOWN:case WM_MBUTTONUP:e=sv_event_map("button");sv_event_put(e,"down",sv_bool(m.message==WM_LBUTTONDOWN||m.message==WM_RBUTTONDOWN||m.message==WM_MBUTTONDOWN));sv_event_put(e,"button",sv_int((m.message==WM_LBUTTONDOWN||m.message==WM_LBUTTONUP)?1:(m.message==WM_RBUTTONDOWN||m.message==WM_RBUTTONUP)?2:3));sv_event_put(e,"x",sv_int((int16_t)LOWORD(m.lParam)));sv_event_put(e,"y",sv_int((int16_t)HIWORD(m.lParam)));break;case WM_MOUSEWHEEL:e=sv_event_map("wheel");sv_event_put(e,"delta",sv_int((int16_t)HIWORD(m.wParam)));break;default:TranslateMessage(&m);DispatchMessageW(&m);continue;}if(e.tag!=SV_NULL)return e;}return sv_null();
#endif
}
static SlugValue sv_window_close_value(SlugValue wv){if(wv.tag!=SV_WINDOW||!wv.as.window)sv_fail("window required");sv_window_close_raw(wv.as.window);return sv_null();}

static SlugAudio *sv_require_audio(SlugValue v){if(v.tag!=SV_AUDIO||!v.as.audio||v.as.audio->closed)sv_fail("open audio output required");return v.as.audio;}
static SlugValue sv_audio_open_value(SlugValue ratev,SlugValue chv){int64_t rate=sv_int_num(ratev),ch=sv_int_num(chv);if(rate<8000||rate>384000||ch<1||ch>8)sv_fail("audio format out of range");
#ifndef _WIN32
sv_fail("audio capability unavailable on this platform");return sv_null();
#else
WAVEFORMATEX fmt;memset(&fmt,0,sizeof(fmt));fmt.wFormatTag=WAVE_FORMAT_PCM;fmt.nChannels=(WORD)ch;fmt.nSamplesPerSec=(DWORD)rate;fmt.wBitsPerSample=16;fmt.nBlockAlign=(WORD)(ch*2);fmt.nAvgBytesPerSec=(DWORD)(rate*fmt.nBlockAlign);HWAVEOUT out=NULL;if(waveOutOpen(&out,WAVE_MAPPER,&fmt,0,0,CALLBACK_NULL)!=MMSYSERR_NOERROR)sv_fail("audio open failed");SlugAudio *a=(SlugAudio*)sv_heap_alloc(sizeof(SlugAudio),SH_AUDIO);a->closed=false;a->rate=(uint32_t)rate;a->channels=(uint16_t)ch;a->out=out;return sv_audio_value(a);
#endif
}
static SlugValue sv_audio_submit(SlugValue av,SlugValue bv){SlugAudio *a=sv_require_audio(av);if(bv.tag!=SV_BYTES||!bv.as.bytes)sv_fail("audio submit requires bytes");size_t n=bv.as.bytes->len;if(n%((size_t)a->channels*2)!=0)sv_fail("S16LE PCM length is not frame-aligned");
#ifndef _WIN32
(void)n;sv_fail("audio capability unavailable on this platform");return sv_null();
#else
if(n>UINT32_MAX)sv_fail("audio buffer too large");WAVEHDR h;memset(&h,0,sizeof(h));h.lpData=(LPSTR)bv.as.bytes->data;h.dwBufferLength=(DWORD)n;if(waveOutPrepareHeader(a->out,&h,sizeof(h))!=MMSYSERR_NOERROR)sv_fail("audio prepare failed");if(waveOutWrite(a->out,&h,sizeof(h))!=MMSYSERR_NOERROR){waveOutUnprepareHeader(a->out,&h,sizeof(h));sv_fail("audio submit failed");}while(!(h.dwFlags&WHDR_DONE))Sleep(1);while(waveOutUnprepareHeader(a->out,&h,sizeof(h))==WAVERR_STILLPLAYING)Sleep(1);return sv_null();
#endif
}
static SlugValue sv_audio_close_value(SlugValue av){if(av.tag!=SV_AUDIO||!av.as.audio)sv_fail("audio output required");sv_audio_close_raw(av.as.audio);return sv_null();}

static SlugDevice *sv_require_device(SlugValue v){if(v.tag!=SV_DEVICE||!v.as.device||v.as.device->closed)sv_fail("open device required");return v.as.device;}
static SlugDevice *sv_device_alloc(void){SlugDevice *d=(SlugDevice*)sv_heap_alloc(sizeof(SlugDevice),SH_DEVICE);d->closed=false;
#ifdef _WIN32
d->h=INVALID_HANDLE_VALUE;
#else
d->fd=-1;
#endif
return d;}
static SlugValue sv_device_open_value(SlugValue pathv,SlugValue modev){const char *path=sv_require_string(pathv,"device path must be string"),*mode=sv_require_string(modev,"device mode must be string");SlugDevice *d=sv_device_alloc();
#ifdef _WIN32
DWORD access=0;if(strcmp(mode,"r")==0)access=GENERIC_READ;else if(strcmp(mode,"w")==0)access=GENERIC_WRITE;else if(strcmp(mode,"rw")==0||strcmp(mode,"wr")==0)access=GENERIC_READ|GENERIC_WRITE;else sv_fail("device mode must be r, w, or rw");wchar_t *wp=sv_widen(path);d->h=CreateFileW(wp,access,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_EXISTING,0,NULL);free(wp);if(d->h==INVALID_HANDLE_VALUE)sv_fail("device open failed");
#else
int flags;if(strcmp(mode,"r")==0)flags=O_RDONLY;else if(strcmp(mode,"w")==0)flags=O_WRONLY;else if(strcmp(mode,"rw")==0||strcmp(mode,"wr")==0)flags=O_RDWR;else sv_fail("device mode must be r, w, or rw");d->fd=open(path,flags);if(d->fd<0)sv_fail("device open failed");
#endif
return sv_device_value(d);}
#ifndef _WIN32
static speed_t sv_serial_speed(uint64_t b){switch(b){case 50:return B50;case 75:return B75;case 110:return B110;case 300:return B300;case 600:return B600;case 1200:return B1200;case 2400:return B2400;case 4800:return B4800;case 9600:return B9600;case 19200:return B19200;case 38400:return B38400;
#ifdef B57600
case 57600:return B57600;
#endif
#ifdef B115200
case 115200:return B115200;
#endif
#ifdef B230400
case 230400:return B230400;
#endif
default:sv_fail("unsupported serial baud");return B9600;}}
#endif
static SlugValue sv_serial_open_value(SlugValue pathv,SlugValue baudv){const char *path=sv_require_string(pathv,"serial path must be string");uint64_t baud=sv_u64_numeric(baudv);SlugDevice *d=sv_device_alloc();
#ifdef _WIN32
wchar_t *wp=sv_widen(path);d->h=CreateFileW(wp,GENERIC_READ|GENERIC_WRITE,0,NULL,OPEN_EXISTING,0,NULL);free(wp);if(d->h==INVALID_HANDLE_VALUE)sv_fail("serial open failed");DCB dc;memset(&dc,0,sizeof(dc));dc.DCBlength=sizeof(dc);if(!GetCommState(d->h,&dc))sv_fail("serial configuration failed");dc.BaudRate=(DWORD)baud;dc.ByteSize=8;dc.Parity=NOPARITY;dc.StopBits=ONESTOPBIT;dc.fBinary=TRUE;dc.fParity=FALSE;if(!SetCommState(d->h,&dc))sv_fail("serial configuration failed");COMMTIMEOUTS to={0};to.ReadIntervalTimeout=MAXDWORD;to.ReadTotalTimeoutConstant=100;SetCommTimeouts(d->h,&to);
#else
d->fd=open(path,O_RDWR|O_NOCTTY);if(d->fd<0)sv_fail("serial open failed");struct termios t;if(tcgetattr(d->fd,&t)!=0)sv_fail("serial configuration failed");speed_t sp=sv_serial_speed(baud);if(cfsetispeed(&t,sp)!=0||cfsetospeed(&t,sp)!=0)sv_fail("serial configuration failed");t.c_cflag&=~(PARENB|CSTOPB|CSIZE);t.c_cflag|=CS8|CLOCAL|CREAD;t.c_iflag&=~(IXON|IXOFF|IXANY);t.c_lflag&=~(ICANON|ECHO|ECHOE|ISIG);t.c_oflag&=~OPOST;t.c_cc[VMIN]=0;t.c_cc[VTIME]=1;if(tcsetattr(d->fd,TCSANOW,&t)!=0)sv_fail("serial configuration failed");
#endif
return sv_device_value(d);}
static SlugValue sv_device_read_value(SlugValue dv,SlugValue nv){SlugDevice *d=sv_require_device(dv);int64_t m=sv_int_num(nv);if(m<0||m>16777216)sv_fail("device read length out of range");size_t n=(size_t)m;unsigned char *buf=n?(unsigned char*)sv_xmalloc(n):NULL;size_t got=0;
#ifdef _WIN32
DWORD r=0;if(n&&!ReadFile(d->h,buf,(DWORD)n,&r,NULL)){free(buf);sv_fail("device read failed");}got=(size_t)r;
#else
ssize_t r;do{r=n?read(d->fd,buf,n):0;}while(r<0&&errno==EINTR);if(r<0){free(buf);sv_fail("device read failed");}got=(size_t)r;
#endif
SlugValue out=sv_bytes(buf,got);free(buf);return out;}
static SlugValue sv_device_write_value(SlugValue dv,SlugValue bv){SlugDevice *d=sv_require_device(dv);if(bv.tag!=SV_BYTES||!bv.as.bytes)sv_fail("device write requires bytes");const unsigned char *p=bv.as.bytes->data;size_t n=bv.as.bytes->len,wrote=0;while(wrote<n){
#ifdef _WIN32
DWORD chunk=(DWORD)((n-wrote)>UINT32_MAX?UINT32_MAX:(n-wrote)),r=0;if(!WriteFile(d->h,p+wrote,chunk,&r,NULL)||r==0)sv_fail("device write failed");wrote+=(size_t)r;
#else
ssize_t r=write(d->fd,p+wrote,n-wrote);if(r<0&&errno==EINTR)continue;if(r<=0)sv_fail("device write failed");wrote+=(size_t)r;
#endif
}if(wrote>(size_t)INT64_MAX)sv_fail("device write count overflow");return sv_int((int64_t)wrote);}
static SlugValue sv_device_close_value(SlugValue dv){if(dv.tag!=SV_DEVICE||!dv.as.device)sv_fail("device required");sv_device_close_raw(dv.as.device);return sv_null();}

static bool sv_string_is_ascii_literal(SlugValue v,const char *lit){if(v.tag!=SV_STRING||!lit)return false;size_t n=strlen(lit);return sv_string_bytes(v.as.s)==n&&(!n||memcmp(v.as.s,lit,n)==0);}
static SlugValue sv_capability_present(SlugValue name){
    if(name.tag!=SV_STRING)return sv_bool(false);
    const char *always[]={
        "@std/sys.av","@std/sys.ev","@std/sys.cw","@std/sys.pf","@std/sys.cp","@std/sys.pc",
        "@std/time.tm","@std/time.mt","@std/time.wt","@std/rand.en",
        "@std/fs.fr","@std/fs.ft","@std/fs.fw","@std/fs.fa","@std/fs.fe","@std/fs.fd","@std/fs.fm","@std/fs.md","@std/fs.rm","@std/fs.mv","@std/fs.fo","@std/fs.hr","@std/fs.hw","@std/fs.hs","@std/fs.hp","@std/fs.hf","@std/fs.hc",
        "@std/net.so","@std/net.cn","@std/net.bn","@std/net.ls","@std/net.ac","@std/net.sd","@std/net.rc","@std/net.sc","@std/net.gp",
        "@std/gfx.sf","@std/gfx.px","@std/gfx.rf","@std/gfx.dl","@std/gfx.sb",
        "@std/dev.do","@std/dev.dv","@std/dev.dr","@std/dev.dw","@std/dev.dx",
        "@std/list.ap","@std/list.ip","@std/list.rm","@std/list.pp"};
    for(size_t i=0;i<sizeof(always)/sizeof(always[0]);i++)if(sv_string_is_ascii_literal(name,always[i]))return sv_bool(true);
#ifdef _WIN32
    const char *win[]={"@std/gfx.wn","@std/gfx.wf","@std/gfx.pe","@std/gfx.wx","@std/audio.au","@std/audio.aq","@std/audio.ax"};
    for(size_t i=0;i<sizeof(win)/sizeof(win[0]);i++)if(sv_string_is_ascii_literal(name,win[i]))return sv_bool(true);
#endif
    return sv_bool(false);
}
/* Registry-facing builtin ABI: every native capability is (argc, argv) -> value. */
static SlugValue sv_builtin_co(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("co arity");return sv_co(argv[0]);}
static SlugValue sv_builtin_ci(size_t argc,SlugValue *argv){if(argc>1)sv_fail("ci arity");return sv_ci(argc?argv[0]:sv_string(""));}
static SlugValue sv_builtin_ty(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("ty arity");return sv_typeof_value(argv[0]);}
static SlugValue sv_builtin_cv(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("cv arity");return sv_can_convert_value(argv[0],argv[1]);}
static SlugValue sv_builtin_in(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("in arity");return sv_in(argv[0],argv[1]);}
static SlugValue sv_builtin_iv(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("iv arity");return sv_iv(argv[0],argv[1]);}
static SlugValue sv_builtin_ln(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("ln arity");return sv_ln(argv[0]);}
static SlugValue sv_builtin_sl(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("sl arity");return sv_sl(argv[0]);}
static SlugValue sv_builtin_by(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("by arity");return sv_by(argv[0]);}
static SlugValue sv_builtin_list_ap(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("LI.ap arity");return sv_list_api_append(argv[0],argv[1]);}
static SlugValue sv_builtin_list_ip(size_t argc,SlugValue *argv){if(argc!=3)sv_fail("LI.ip arity");return sv_list_api_insert(argv[0],argv[1],argv[2]);}
static SlugValue sv_builtin_list_rm(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("LI.rm arity");return sv_list_api_remove(argv[0],argv[1]);}
static SlugValue sv_builtin_list_pp(size_t argc,SlugValue *argv){if(argc<1||argc>2)sv_fail("LI.pp arity");return sv_list_api_pop(argv[0],argc==2,argc==2?argv[1]:sv_null());}
static SlugValue sv_builtin_cli_ex(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("internal cli ex arity");return sv_cli_exit_value(argv[0]);}
static SlugValue sv_builtin_cli_se(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("internal cli se arity");return sv_cli_stderr_value(argv[0]);}
static SlugValue sv_builtin_cli_so(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("internal cli so arity");return sv_cli_stdout_value(argv[0]);}
static SlugValue sv_builtin_cli_ep(size_t argc,SlugValue *argv){(void)argv;if(argc)sv_fail("internal cli ep arity");return sv_cli_executable_path_value();}
static SlugValue sv_builtin_av(size_t argc,SlugValue *argv){(void)argv;if(argc)sv_fail("av arity");return sv_args_value();}
static SlugValue sv_builtin_ev(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("ev arity");return sv_env_value(sv_require_string(argv[0],"ev requires string"));}
static SlugValue sv_builtin_cw(size_t argc,SlugValue *argv){(void)argv;if(argc)sv_fail("cw arity");return sv_cwd_value();}
static SlugValue sv_builtin_pf(size_t argc,SlugValue *argv){(void)argv;if(argc)sv_fail("pf arity");return sv_platform_value();}
static SlugValue sv_builtin_cp(size_t argc,SlugValue *argv){if(argc!=1)return sv_bool(false);return sv_capability_present(argv[0]);}
static SlugValue sv_builtin_tm(size_t argc,SlugValue *argv){(void)argv;if(argc)sv_fail("tm arity");return sv_float(sv_wall_seconds());}
static SlugValue sv_builtin_mt(size_t argc,SlugValue *argv){(void)argv;if(argc)sv_fail("mt arity");return sv_float(sv_mono_seconds());}
static SlugValue sv_builtin_wt(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("wt arity");return sv_wait_seconds(argv[0]);}
static SlugValue sv_builtin_en(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("en arity");return sv_entropy_value(argv[0]);}
static SlugValue sv_builtin_fr(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("fr arity");return sv_read_file_bytes(sv_require_string(argv[0],"fr requires path string"));}
static SlugValue sv_builtin_ft(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("ft arity");return sv_read_file_text(sv_require_string(argv[0],"ft requires path string"));}
static SlugValue sv_builtin_fw(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("fw arity");return sv_write_file(sv_require_string(argv[0],"fw requires path string"),argv[1],false);}
static SlugValue sv_builtin_fa(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("fa arity");return sv_write_file(sv_require_string(argv[0],"fa requires path string"),argv[1],true);}
static SlugValue sv_builtin_fe(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("fe arity");return sv_file_exists(sv_require_string(argv[0],"fe requires path string"));}
static SlugValue sv_builtin_fd(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("fd arity");return sv_dir_list(sv_require_string(argv[0],"fd requires path string"));}
static SlugValue sv_builtin_fm(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("fm arity");return sv_file_meta(sv_require_string(argv[0],"fm requires path string"));}
static SlugValue sv_builtin_md(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("md arity");return sv_make_dir(sv_require_string(argv[0],"md requires path string"));}
static SlugValue sv_builtin_rm(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("rm arity");return sv_remove_path(sv_require_string(argv[0],"rm requires path string"));}
static SlugValue sv_builtin_mv(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("mv arity");return sv_move_path(sv_require_string(argv[0],"mv requires path strings"),sv_require_string(argv[1],"mv requires path strings"));}
static SlugValue sv_builtin_fo(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("fo arity");return sv_file_open_value(argv[0],argv[1]);}
static SlugValue sv_builtin_hr(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("hr arity");return sv_file_handle_read(argv[0],argv[1]);}
static SlugValue sv_builtin_hw(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("hw arity");return sv_file_handle_write(argv[0],argv[1]);}
static SlugValue sv_builtin_hs(size_t argc,SlugValue *argv){if(argc!=3)sv_fail("hs arity");return sv_file_seek_value(argv[0],argv[1],argv[2]);}
static SlugValue sv_builtin_hp(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("hp arity");return sv_file_tell_value(argv[0]);}
static SlugValue sv_builtin_hf(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("hf arity");return sv_file_flush_value(argv[0]);}
static SlugValue sv_builtin_hc(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("hc arity");return sv_file_close_value(argv[0]);}
static SlugValue sv_builtin_pc(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("pc arity");return sv_process_run(argv[0]);}
static SlugValue sv_builtin_so(size_t argc,SlugValue *argv){(void)argv;if(argc)sv_fail("so arity");return sv_socket_new_tcp();}
static SlugValue sv_builtin_cn(size_t argc,SlugValue *argv){if(argc!=3)sv_fail("cn arity");return sv_socket_connect(argv[0],argv[1],argv[2]);}
static SlugValue sv_builtin_bn(size_t argc,SlugValue *argv){if(argc!=3)sv_fail("bn arity");return sv_socket_bind(argv[0],argv[1],argv[2]);}
static SlugValue sv_builtin_ls(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("ls arity");return sv_socket_listen(argv[0],argv[1]);}
static SlugValue sv_builtin_ac(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("ac arity");return sv_socket_accept(argv[0]);}
static SlugValue sv_builtin_sd(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("sd arity");return sv_socket_send(argv[0],argv[1]);}
static SlugValue sv_builtin_rc(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("rc arity");return sv_socket_recv(argv[0],argv[1]);}
static SlugValue sv_builtin_sc(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("sc arity");return sv_socket_close(argv[0]);}
static SlugValue sv_builtin_gp(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("gp arity");return sv_socket_port(argv[0]);}
static SlugValue sv_builtin_sf(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("sf arity");return sv_surface_new_value(argv[0],argv[1]);}
static SlugValue sv_builtin_px(size_t argc,SlugValue *argv){if(argc!=4)sv_fail("px arity");return sv_surface_pixel(argv[0],argv[1],argv[2],argv[3]);}
static SlugValue sv_builtin_rf(size_t argc,SlugValue *argv){if(argc!=6)sv_fail("rf arity");return sv_surface_rect(argv[0],argv[1],argv[2],argv[3],argv[4],argv[5]);}
static SlugValue sv_builtin_dl(size_t argc,SlugValue *argv){if(argc!=6)sv_fail("dl arity");return sv_surface_line(argv[0],argv[1],argv[2],argv[3],argv[4],argv[5]);}
static SlugValue sv_builtin_sb(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("sb arity");return sv_surface_bytes(argv[0]);}
static SlugValue sv_builtin_wn(size_t argc,SlugValue *argv){if(argc!=3)sv_fail("wn arity");return sv_window_new_value(argv[0],argv[1],argv[2]);}
static SlugValue sv_builtin_wf(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("wf arity");return sv_window_present(argv[0],argv[1]);}
static SlugValue sv_builtin_pe(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("pe arity");return sv_window_poll(argv[0]);}
static SlugValue sv_builtin_wx(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("wx arity");return sv_window_close_value(argv[0]);}
static SlugValue sv_builtin_au(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("au arity");return sv_audio_open_value(argv[0],argv[1]);}
static SlugValue sv_builtin_aq(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("aq arity");return sv_audio_submit(argv[0],argv[1]);}
static SlugValue sv_builtin_ax(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("ax arity");return sv_audio_close_value(argv[0]);}
static SlugValue sv_builtin_do(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("do arity");return sv_device_open_value(argv[0],argv[1]);}
static SlugValue sv_builtin_dv(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("dv arity");return sv_serial_open_value(argv[0],argv[1]);}
static SlugValue sv_builtin_dr(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("dr arity");return sv_device_read_value(argv[0],argv[1]);}
static SlugValue sv_builtin_dw(size_t argc,SlugValue *argv){if(argc!=2)sv_fail("dw arity");return sv_device_write_value(argv[0],argv[1]);}
static SlugValue sv_builtin_dx(size_t argc,SlugValue *argv){if(argc!=1)sv_fail("dx arity");return sv_device_close_value(argv[0]);}
