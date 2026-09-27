from __future__ import annotations

import json
from dataclasses import dataclass, fields, field

from . import ast
from .builtins import builtin
from .diagnostics import CodegenError
from .ir import IRModule, lower_ir
from .mir import lower_mir
from .optimizer import ConstValue, OptimizerResult, optimize_mir


_RUNTIME = r'''
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
typedef struct SlugExcState SlugExcState;
typedef struct SlugScopeFrame SlugScopeFrame;
typedef struct SlugScopeState SlugScopeState;
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
    union { int64_t i; uint64_t u; double f; SlugString *s; SlugBytes *bytes; SlugSocket *sock; SlugFile *file; SlugSurface *surface; SlugWindow *window; SlugAudio *audio; SlugDevice *device; bool b; SlugList *list; SlugMap *map; SlugObject *obj; SlugClosure *closure; SlugErrorValue *err; } as;
};
struct SlugString { SvHeap heap; size_t len, cp_len; bool ascii; unsigned char data[]; };
struct SlugBytes { SvHeap heap; size_t len; unsigned char *data; };
struct SlugSocket { SvHeap heap; SvSocketHandle h; bool closed; };
struct SlugFile { SvHeap heap; FILE *f; bool closed; };
struct SlugSurface { SvHeap heap; size_t width,height,len; unsigned char *pixels; };
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
struct SlugScopeFrame { SlugScopeState *state; };
struct SlugScopeState { SlugScopeState *prev; SlugScopeFrame *owner; size_t temp_base; size_t len,cap; SlugCell **cells; };
struct SlugExcFrame { SlugExcState *state; };
struct SlugExcState { jmp_buf env; SlugExcState *prev; SlugExcFrame *owner; SlugScopeState *scope_base; size_t temp_base, eval_base; SlugValue error; };

static SvHeap *sv_heap_head=NULL;
static size_t sv_heap_allocated=0,sv_heap_freed=0,sv_heap_peak=0,sv_gc_collections=0;
static SlugScopeState *sv_scope_top=NULL;
static SlugExcState *sv_exc_top=NULL;
static SlugValue **sv_root_slots=NULL; static size_t sv_root_slots_len=0,sv_root_slots_cap=0;
static SlugValue *sv_temp_roots=NULL; static size_t sv_temp_roots_len=0,sv_temp_roots_cap=0;
static size_t *sv_eval_marks=NULL; static size_t sv_eval_marks_len=0,sv_eval_marks_cap=0;
static bool sv_gc_running=false,sv_runtime_stopped=false;
static bool sv_gc_policy_loaded=false; static size_t sv_gc_interval=65536,sv_gc_safepoints=0;
static int sv_argc=0; static char **sv_argv=NULL;
static void (*sv_object_destructor)(SlugObject*)=NULL;

static void sv_fail(const char *msg);
static void sv_fail_kind(const char *kind,const char *msg);
static void sv_report_uncaught(SlugValue e);
static bool sv_utf8_valid(const unsigned char *s,size_t n);
static void sv_gc_collect(void);
static void sv_gc_safepoint(void);
static bool sv_runtime_shutdown(void);
static size_t sv_temp_root_push(SlugValue v);
static size_t sv_temp_root_mark(void);
static void sv_temp_root_pop(size_t mark);
static SlugValue sv_list_empty(bool frozen);
static SlugValue sv_list_from(SlugValue *items,size_t n,bool frozen);
static bool sv_size_add(size_t a,size_t b,size_t *out){if(a>SIZE_MAX-b)return false;*out=a+b;return true;}
static bool sv_size_mul(size_t a,size_t b,size_t *out){if(a&&b>SIZE_MAX/a)return false;*out=a*b;return true;}
static size_t sv_size_add_or_fail(size_t a,size_t b,const char *what){size_t n;if(!sv_size_add(a,b,&n))sv_fail_kind("resource",what);return n;}
static size_t sv_size_mul_or_fail(size_t a,size_t b,const char *what){size_t n;if(!sv_size_mul(a,b,&n))sv_fail_kind("resource",what);return n;}
static size_t sv_grow_capacity(size_t cap,size_t need){
    size_t n=cap?cap:4;if(n>=need)return n;
    while(n<need){size_t next;if(!sv_size_mul(n,2,&next)||next<=n){n=need;break;}n=next;}
    return n;
}
static void *sv_xmalloc(size_t n){ void *p=malloc(n?n:1); if(!p){perror("malloc"); exit(70);} return p; }
static void *sv_xrealloc(void *p,size_t n){ void *q=realloc(p,n?n:1); if(!q){perror("realloc"); exit(70);} return q; }
static char *sv_dup_n(const char *x,size_t n){size_t z=sv_size_add_or_fail(n,1,"string size overflow");char *p=(char*)sv_xmalloc(z);if(n)memcpy(p,x,n);p[n]='\0';return p;}
static char *sv_dup(const char *x){ return sv_dup_n(x,strlen(x)); }
static void *sv_heap_alloc(size_t n,SvHeapKind kind){
    SvHeap *h=(SvHeap*)sv_xmalloc(n);memset(h,0,n);h->kind=kind;h->next=sv_heap_head;if(sv_heap_head)sv_heap_head->prev=h;sv_heap_head=h;sv_heap_allocated++;size_t live=sv_heap_allocated-sv_heap_freed;if(live>sv_heap_peak)sv_heap_peak=live;return h;
}
static void sv_heap_unlink(SvHeap *h){if(h->prev)h->prev->next=h->next;else sv_heap_head=h->next;if(h->next)h->next->prev=h->prev;sv_heap_freed++;}

static SlugValue sv_null(void){ SlugValue v={.tag=SV_NULL}; return v; }
static SlugValue sv_int(int64_t x){ SlugValue v={.tag=SV_INT}; v.as.i=x; return v; }
static SlugValue sv_uint(uint64_t x){ SlugValue v={.tag=SV_UINT}; v.as.u=x; return v; }
static SlugValue sv_float(double x){if(!isfinite(x))sv_fail_kind("range","non-finite float");SlugValue v={.tag=SV_FLOAT}; v.as.f=x; return v; }
static SlugValue sv_bool(bool x){ SlugValue v={.tag=SV_BOOL}; v.as.b=x; return v; }
static SlugValue sv_string_n(const unsigned char *x,size_t n){
    if(n&&!sv_utf8_valid(x,n))sv_fail_kind("encoding","invalid UTF-8 string");
    size_t payload=sv_size_add_or_fail(n,1,"string size overflow");
    size_t total=sv_size_add_or_fail(sizeof(SlugString),payload,"string size overflow");
    SlugString *o=(SlugString*)sv_heap_alloc(total,SH_STRING);o->len=n;o->cp_len=0;o->ascii=true;
    for(size_t i=0;i<n;i++){unsigned char c=x[i];if(c&0x80)o->ascii=false;if((c&0xC0)!=0x80)o->cp_len++;}
    if(n)memcpy(o->data,x,n);o->data[n]=0;
    SlugValue v={.tag=SV_STRING};v.as.s=o;return v;
}
static SlugValue sv_string(const char *x){return sv_string_n((const unsigned char*)(x?x:""),x?strlen(x):0);}
static SlugValue sv_string_owned_n(unsigned char *x,size_t n){SlugValue v=sv_string_n(x,n);free(x);return v;}
static SlugValue sv_string_owned(char *x){size_t n=x?strlen(x):0;SlugValue v=sv_string_n((const unsigned char*)(x?x:""),n);free(x);return v;}
static const unsigned char *sv_str_data(SlugValue v){return (v.tag==SV_STRING&&v.as.s)?v.as.s->data:(const unsigned char*)"";}
static size_t sv_str_len(SlugValue v){return (v.tag==SV_STRING&&v.as.s)?v.as.s->len:0;}
static size_t sv_str_cp_len(SlugValue v){return (v.tag==SV_STRING&&v.as.s)?v.as.s->cp_len:0;}
static bool sv_str_ascii(SlugValue v){return v.tag==SV_STRING&&v.as.s&&v.as.s->ascii;}
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

static void sv_scope_state_leave(SlugScopeState *st){if(sv_scope_top!=st)sv_fail("scope stack corruption");sv_scope_top=st->prev;sv_temp_root_pop(st->temp_base);free(st->cells);if(st->owner)st->owner->state=NULL;free(st);}
static void sv_scope_enter(SlugScopeFrame *f){SlugScopeState *st=(SlugScopeState*)sv_xmalloc(sizeof(*st));memset(st,0,sizeof(*st));st->prev=sv_scope_top;st->owner=f;st->temp_base=sv_temp_roots_len;f->state=st;sv_scope_top=st;}
static void sv_scope_track(SlugCell *c){if(!sv_scope_top){c->permanent_root=true;return;}SlugScopeState *f=sv_scope_top;if(f->len==f->cap){f->cap=sv_grow_capacity(f->cap,sv_size_add_or_fail(f->len,1,"scope length overflow"));f->cells=(SlugCell**)sv_xrealloc(f->cells,sv_size_mul_or_fail(sizeof(SlugCell*),f->cap,"scope capacity overflow"));}f->cells[f->len++]=c;}
static void sv_scope_leave(SlugScopeFrame *f){if(!f||!f->state||sv_scope_top!=f->state)sv_fail("scope stack corruption");sv_scope_state_leave(f->state);}
static void sv_scope_unwind_to(SlugScopeState *base){while(sv_scope_top&&sv_scope_top!=base)sv_scope_state_leave(sv_scope_top);if(base&&!sv_scope_top)sv_fail("scope unwind target missing");}
static void sv_scope_unwind_through(SlugScopeFrame *target){SlugScopeState *want=target?target->state:NULL;while(sv_scope_top){SlugScopeState *f=sv_scope_top;bool hit=f==want;sv_scope_state_leave(f);if(hit)return;}sv_fail("scope unwind target missing");}
static SlugCell *sv_cell_new(void){ SlugCell *c=(SlugCell*)sv_heap_alloc(sizeof(SlugCell),SH_CELL);c->permanent_root=false;c->heap_owned=true;c->value=sv_null();sv_scope_track(c);return c; }
static void sv_stack_cell_init(SlugCell *c){memset(c,0,sizeof(*c));c->heap.kind=SH_CELL;c->permanent_root=false;c->heap_owned=false;c->value=sv_null();sv_scope_track(c);}
static SlugCell *sv_cell_from(SlugValue v){SlugCell *c=sv_cell_new();c->value=v;return c;}
static SlugClosure *sv_closure_new(SlugClosureFn fn,size_t n,SlugCell **captures){
    SlugClosure *c=(SlugClosure*)sv_heap_alloc(sizeof(SlugClosure),SH_CLOSURE);c->fn=fn;c->capture_count=n;
    size_t bytes=sv_size_mul_or_fail(sizeof(SlugCell*),n,"closure capture allocation overflow");c->captures=n?(SlugCell**)sv_xmalloc(bytes):NULL;if(n)memcpy(c->captures,captures,bytes);return c;
}
static SlugResult sv_invoke(SlugValue callable,size_t argc,SlugValue *argv){
    if(callable.tag!=SV_CALLABLE||!callable.as.closure||!callable.as.closure->fn)sv_fail("callable value required");
    return callable.as.closure->fn(callable.as.closure,argc,argv);
}
/* Audited v1 evaluation sequencer. C does not define function-argument
   evaluation order, so generated composite expressions never place multiple SLUG
   subexpressions directly into one C call. They are pushed left-to-right through
   comma operators, remain GC-rooted, and are consumed by one of these helpers. */
typedef SlugResult (*SvDirectFn)(size_t,SlugValue*);
typedef SlugResult (*SvMethodFn)(SlugObject*,size_t,SlugValue*);
typedef SlugValue (*SvValueFn)(size_t,SlugValue*);
typedef void (*SvInitFn)(SlugObject*,size_t,SlugValue*);
typedef SlugValue (*SvBinaryFn)(SlugValue,SlugValue);
typedef bool (*SvBoolBinaryFn)(SlugValue,SlugValue);
typedef int (*SvCompareFn)(SlugValue,SlugValue);
static void sv_eval_begin(void){
    if(sv_eval_marks_len==sv_eval_marks_cap){sv_eval_marks_cap=sv_grow_capacity(sv_eval_marks_cap,sv_size_add_or_fail(sv_eval_marks_len,1,"evaluation mark overflow"));sv_eval_marks=(size_t*)sv_xrealloc(sv_eval_marks,sv_size_mul_or_fail(sizeof(size_t),sv_eval_marks_cap,"evaluation mark allocation overflow"));}
    sv_eval_marks[sv_eval_marks_len++]=sv_temp_roots_len;
}
static size_t sv_eval_base(void){if(!sv_eval_marks_len)sv_fail("evaluation stack underflow");return sv_eval_marks[sv_eval_marks_len-1];}
static size_t sv_eval_count(void){size_t b=sv_eval_base();if(b>sv_temp_roots_len)sv_fail("evaluation root corruption");return sv_temp_roots_len-b;}
static void sv_eval_push(SlugValue v){(void)sv_temp_root_push(v);}
static SlugValue *sv_eval_argv(size_t skip){size_t b=sv_eval_base(),n=sv_eval_count();if(skip>n)sv_fail("evaluation argument underflow");return n==skip?NULL:sv_temp_roots+b+skip;}
static void sv_eval_finish(void){size_t b=sv_eval_base();sv_temp_root_pop(b);sv_eval_marks_len--;}
static SlugResult sv_eval_call_result(SvDirectFn fn){size_t n=sv_eval_count();SlugResult r=fn(n,sv_eval_argv(0));sv_eval_finish();return r;}
static SlugResult sv_eval_call_method(SvMethodFn fn){size_t n=sv_eval_count();if(n<1)sv_fail("method receiver missing");SlugValue recv=sv_eval_argv(0)[0];if(recv.tag!=SV_OBJECT||!recv.as.obj)sv_fail_kind("type","object receiver required");SlugResult r=fn(recv.as.obj,n-1,sv_eval_argv(1));sv_eval_finish();return r;}
static SlugResult sv_eval_invoke(void){size_t n=sv_eval_count();if(n<1)sv_fail("callable missing");SlugValue fn=sv_eval_argv(0)[0];SlugResult r=sv_invoke(fn,n-1,sv_eval_argv(1));sv_eval_finish();return r;}
static SlugValue sv_eval_call_value(SvValueFn fn){size_t n=sv_eval_count();SlugValue v=fn(n,sv_eval_argv(0));sv_eval_finish();return v;}
static void sv_eval_call_init(SvInitFn fn){size_t n=sv_eval_count();if(n<1)sv_fail("initializer receiver missing");SlugValue recv=sv_eval_argv(0)[0];if(recv.tag!=SV_OBJECT||!recv.as.obj)sv_fail_kind("type","object receiver required");fn(recv.as.obj,n-1,sv_eval_argv(1));sv_eval_finish();}
static SlugValue sv_eval_binary(SvBinaryFn fn){if(sv_eval_count()!=2)sv_fail("binary evaluation arity");SlugValue *a=sv_eval_argv(0);SlugValue v=fn(a[0],a[1]);sv_eval_finish();return v;}
static bool sv_eval_bool_binary(SvBoolBinaryFn fn){if(sv_eval_count()!=2)sv_fail("boolean evaluation arity");SlugValue *a=sv_eval_argv(0);bool v=fn(a[0],a[1]);sv_eval_finish();return v;}
static int sv_eval_compare(SvCompareFn fn){if(sv_eval_count()!=2)sv_fail("comparison evaluation arity");SlugValue *a=sv_eval_argv(0);int v=fn(a[0],a[1]);sv_eval_finish();return v;}
static SlugValue sv_error_new(const char *kind,const char *message,SlugValue payload,SlugValue cause,SlugValue suppressed){
    if(cause.tag!=SV_NULL&&cause.tag!=SV_ERROR)sv_fail("internal error cause must be ER or nn");
    if(suppressed.tag==SV_NULL)suppressed=sv_list_empty(true);
    if(suppressed.tag!=SV_LIST||!suppressed.as.list||!suppressed.as.list->frozen)sv_fail("internal suppressed errors must be a frozen list");
    for(size_t i=0;i<suppressed.as.list->len;i++)if(suppressed.as.list->items[i].tag!=SV_ERROR)sv_fail("internal suppressed entry must be ER");
    SlugErrorValue *e=(SlugErrorValue*)sv_heap_alloc(sizeof(SlugErrorValue),SH_ERROR);e->kind=sv_string(kind?kind:"state");e->message=sv_string(message?message:"");e->payload=payload;e->cause=cause;e->suppressed=suppressed;return sv_error_value(e);
}
static SlugValue sv_wrap_error(SlugValue payload){if(payload.tag==SV_ERROR)return payload;return sv_error_new("user","user error",payload,sv_null(),sv_null());}
static size_t sv_temp_root_push(SlugValue v){size_t mark=sv_temp_roots_len;if(sv_temp_roots_len==sv_temp_roots_cap){sv_temp_roots_cap=sv_grow_capacity(sv_temp_roots_cap,sv_size_add_or_fail(sv_temp_roots_len,1,"temporary root length overflow"));sv_temp_roots=(SlugValue*)sv_xrealloc(sv_temp_roots,sv_size_mul_or_fail(sizeof(SlugValue),sv_temp_roots_cap,"temporary root capacity overflow"));}sv_temp_roots[sv_temp_roots_len++]=v;return mark;}
static size_t sv_temp_root_mark(void){return sv_temp_roots_len;}
static void sv_temp_root_pop(size_t mark){if(mark>sv_temp_roots_len)sv_fail("temporary root stack corruption");sv_temp_roots_len=mark;}
static void sv_root_slot(SlugValue *slot){if(sv_root_slots_len==sv_root_slots_cap){sv_root_slots_cap=sv_grow_capacity(sv_root_slots_cap,sv_size_add_or_fail(sv_root_slots_len,1,"root slot length overflow"));sv_root_slots=(SlugValue**)sv_xrealloc(sv_root_slots,sv_size_mul_or_fail(sizeof(SlugValue*),sv_root_slots_cap,"root slot capacity overflow"));}sv_root_slots[sv_root_slots_len++]=slot;}
static void sv_exc_push(SlugExcFrame *f){SlugExcState *st=(SlugExcState*)sv_xmalloc(sizeof(*st));memset(st,0,sizeof(*st));st->prev=sv_exc_top;st->owner=f;st->scope_base=sv_scope_top;st->temp_base=sv_temp_roots_len;st->eval_base=sv_eval_marks_len;st->error=sv_null();f->state=st;sv_exc_top=st;}
#define SV_EXC_ENV(fptr) ((fptr)->state->env)
static SlugValue sv_exc_error(SlugExcFrame *f){if(!f||!f->state)sv_fail("exception frame missing");return f->state->error;}
static SlugScopeState *sv_exc_scope_base(SlugExcFrame *f){if(!f||!f->state)sv_fail("exception frame missing");return f->state->scope_base;}
static void sv_exc_pop(SlugExcFrame *f){if(!f||!f->state||sv_exc_top!=f->state)sv_fail("exception frame corruption");SlugExcState *st=f->state;sv_exc_top=st->prev;f->state=NULL;free(st);}
static void sv_raise(SlugValue value){SlugValue e=sv_wrap_error(value);if(!sv_exc_top){sv_report_uncaught(e);exit(66);}SlugExcState *target=sv_exc_top;target->error=e;sv_scope_unwind_to(target->scope_base);sv_temp_root_pop(target->temp_base);if(target->eval_base>sv_eval_marks_len)sv_fail("evaluation stack corruption");sv_eval_marks_len=target->eval_base;longjmp(target->env,1);}
static SlugResult sv_result0(void){ SlugResult r={0,NULL}; return r; }
static SlugResult sv_result_from(const SlugValue *items,size_t n){
    SlugResult r={n,NULL};if(!n)return r;size_t bytes=sv_size_mul_or_fail(sizeof(SlugValue),n,"result allocation overflow");r.values=(SlugValue*)sv_xmalloc(bytes);memcpy(r.values,items,bytes);return r;
}
static SlugResult sv_eval_result_values(void){size_t n=sv_eval_count();SlugResult r=sv_result_from(sv_eval_argv(0),n);sv_eval_finish();return r;}
static void sv_result_dispose(SlugResult r){free(r.values);}
static SlugValue sv_result_first(SlugResult r){if(r.n!=1){size_t n=r.n;sv_result_dispose(r);(void)n;sv_fail_kind("arity","function result arity must be exactly one in value context");}SlugValue v=r.values[0];sv_result_dispose(r);return v;}
static void sv_result_require_arity(SlugResult r,size_t targets){if(r.n!=targets)sv_fail_kind("arity","function result arity does not match assignment targets");}
static SlugValue sv_result_pick(SlugResult r,size_t i){if(i>=r.n)sv_fail_kind("arity","result index out of range");return r.values[i];}
static void sv_result_discard(SlugResult r){sv_result_dispose(r);}
static size_t sv_result_root(SlugResult r){size_t mark=sv_temp_roots_len;for(size_t i=0;i<r.n;i++)sv_temp_root_push(r.values[i]);return mark;}

static size_t sv_utf8_next(const char *s,size_t n,size_t i){
    if(i>=n) return n; unsigned char c=(unsigned char)s[i];
    size_t k=(c<0x80)?1:((c&0xE0)==0xC0?2:((c&0xF0)==0xE0?3:((c&0xF8)==0xF0?4:1)));
    return i+k>n?n:i+k;
}
static size_t sv_utf8_len_n(const char *s,size_t n){size_t i=0,c=0;while(i<n){i=sv_utf8_next(s,n,i);c++;}return c;}
static size_t sv_utf8_offset_n(const char *s,size_t n,size_t cp){size_t i=0,c=0;while(i<n&&c<cp){i=sv_utf8_next(s,n,i);c++;}return i;}

static double sv_num(SlugValue v){
    if(v.tag==SV_INT) return (double)v.as.i;
    if(v.tag==SV_UINT) return (double)v.as.u;
    if(v.tag==SV_FLOAT) return v.as.f;
    sv_fail_kind("type","numeric value required"); return 0;
}
static int64_t sv_i64_numeric(SlugValue v){
    if(v.tag==SV_INT)return v.as.i;
    if(v.tag==SV_UINT){if(v.as.u>(uint64_t)INT64_MAX)sv_fail("integer conversion out of range");return (int64_t)v.as.u;}
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
    if(v.tag==SV_FLOAT){double x=v.as.f;if(!isfinite(x)||x<0.0||x>=18446744073709551616.0)sv_fail("unsigned integer conversion out of range");return (uint64_t)x;}
    sv_fail("numeric value required");return 0;
}
static int64_t sv_int_num(SlugValue v){ return sv_i64_numeric(v); }

typedef struct { bool neg; uint64_t mag; bool prefer_unsigned; } SvWideInt;
static SvWideInt sv_wint(SlugValue v){
    if(v.tag==SV_UINT)return (SvWideInt){false,v.as.u,true};
    if(v.tag==SV_INT){if(v.as.i<0){uint64_t m=(uint64_t)(-(v.as.i+1))+1;return (SvWideInt){true,m,false};}return (SvWideInt){false,(uint64_t)v.as.i,false};}
    sv_fail_kind("type","integer value required");return (SvWideInt){false,0,false};
}
static SlugValue sv_wint_value(bool neg,uint64_t mag,bool prefer_unsigned){
    if(mag==0)return prefer_unsigned?sv_uint(0):sv_int(0);
    if(neg){
        const uint64_t lim=UINT64_C(9223372036854775808);if(mag>lim)sv_fail_kind("overflow","integer overflow");
        if(mag==lim)return sv_int(INT64_MIN);return sv_int(-(int64_t)mag);
    }
    if(prefer_unsigned)return sv_uint(mag);
    if(mag>(uint64_t)INT64_MAX)sv_fail_kind("overflow","integer overflow");
    return sv_int((int64_t)mag);
}
static SlugValue sv_wadd(SvWideInt a,SvWideInt b){
    bool pref=a.prefer_unsigned||b.prefer_unsigned;
    if(a.neg==b.neg){if(UINT64_MAX-a.mag<b.mag)sv_fail_kind("overflow","integer overflow");return sv_wint_value(a.neg,a.mag+b.mag,pref&&!a.neg);}
    if(a.mag>=b.mag)return sv_wint_value(a.neg,a.mag-b.mag,pref&&!a.neg);
    return sv_wint_value(b.neg,b.mag-a.mag,pref&&!b.neg);
}
static SlugValue sv_wsub(SvWideInt a,SvWideInt b){b.neg=!b.neg;return sv_wadd(a,b);}
static SlugValue sv_wmul(SvWideInt a,SvWideInt b){
    if(a.mag&&b.mag>UINT64_MAX/a.mag)sv_fail_kind("overflow","integer overflow");
    bool neg=a.neg!=b.neg;return sv_wint_value(neg,a.mag*b.mag,(a.prefer_unsigned||b.prefer_unsigned)&&!neg);
}
static bool sv_truthy(SlugValue v){
    switch(v.tag){
        case SV_NULL: return false; case SV_BOOL: return v.as.b; case SV_INT: return v.as.i!=0; case SV_UINT: return v.as.u!=0;
        case SV_FLOAT: return v.as.f!=0.0; case SV_STRING: return v.as.s && v.as.s->len!=0; case SV_BYTES: return v.as.bytes && v.as.bytes->len!=0; case SV_SOCKET: return v.as.sock!=NULL; case SV_FILE: return v.as.file!=NULL; case SV_SURFACE:return v.as.surface!=NULL; case SV_WINDOW:return v.as.window!=NULL; case SV_AUDIO:return v.as.audio!=NULL; case SV_DEVICE:return v.as.device!=NULL;
        case SV_LIST: return v.as.list && v.as.list->len!=0; case SV_MAP: return v.as.map && v.as.map->len!=0;
        case SV_OBJECT: return v.as.obj!=NULL;
        case SV_CALLABLE: return v.as.closure!=NULL;
        case SV_ERROR: return true;
        case SV_DEFAULT: sv_fail("default placeholder escaped call argument context"); return false;
    } return false;
}

typedef struct { SlugTag tag; const void *a; const void *b; } SvEqSeen;
typedef struct { SlugValue a,b; } SvEqWork;
typedef struct { SvEqSeen *seen; size_t seen_len,seen_cap; SvEqWork *work; size_t work_len,work_cap; } SvEqCtx;
static bool sv_numeric_tag(SlugTag t){return t==SV_INT||t==SV_UINT||t==SV_FLOAT;}
static int sv_cmp_int_float(SlugValue iv,double f){
    if(!isfinite(f))sv_fail("non-finite float escaped runtime");
    if(iv.tag==SV_INT){
        if(f < -9223372036854775808.0)return 1;
        if(f >= 9223372036854775808.0)return -1;
        int64_t fi=(int64_t)f; if(iv.as.i<fi)return -1;if(iv.as.i>fi)return 1;
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
static bool sv_scalar_equal(SlugValue a,SlugValue b){
    if(sv_numeric_tag(a.tag)&&sv_numeric_tag(b.tag))return sv_numeric_compare(a,b)==0;
    if(a.tag!=b.tag)return false;
    switch(a.tag){
        case SV_NULL:return true;case SV_BOOL:return a.as.b==b.as.b;case SV_INT:return a.as.i==b.as.i;case SV_UINT:return a.as.u==b.as.u;case SV_FLOAT:return a.as.f==b.as.f;
        case SV_STRING:return a.as.s==b.as.s||(a.as.s&&b.as.s&&a.as.s->len==b.as.s->len&&(!a.as.s->len||memcmp(a.as.s->data,b.as.s->data,a.as.s->len)==0));
        case SV_BYTES:return a.as.bytes==b.as.bytes||(a.as.bytes&&b.as.bytes&&a.as.bytes->len==b.as.bytes->len&&(!a.as.bytes->len||memcmp(a.as.bytes->data,b.as.bytes->data,a.as.bytes->len)==0));
        case SV_SOCKET:return a.as.sock==b.as.sock;case SV_FILE:return a.as.file==b.as.file;case SV_SURFACE:return a.as.surface==b.as.surface;case SV_WINDOW:return a.as.window==b.as.window;case SV_AUDIO:return a.as.audio==b.as.audio;case SV_DEVICE:return a.as.device==b.as.device;
        case SV_CALLABLE:return a.as.closure==b.as.closure;case SV_DEFAULT:return true;
        default:return false;
    }
}
static bool sv_eq_seen_or_add(SvEqCtx *ctx,SlugTag tag,const void *a,const void *b){
    if(a==b)return true;
    for(size_t i=0;i<ctx->seen_len;i++)if(ctx->seen[i].tag==tag&&ctx->seen[i].a==a&&ctx->seen[i].b==b)return true;
    if(ctx->seen_len==ctx->seen_cap){ctx->seen_cap=sv_grow_capacity(ctx->seen_cap,sv_size_add_or_fail(ctx->seen_len,1,"equality seen length overflow"));ctx->seen=(SvEqSeen*)sv_xrealloc(ctx->seen,sv_size_mul_or_fail(sizeof(SvEqSeen),ctx->seen_cap,"equality seen-set overflow"));}
    ctx->seen[ctx->seen_len++]=(SvEqSeen){tag,a,b};return false;
}
static void sv_eq_push(SvEqCtx *ctx,SlugValue a,SlugValue b){
    if(ctx->work_len==ctx->work_cap){ctx->work_cap=sv_grow_capacity(ctx->work_cap,sv_size_add_or_fail(ctx->work_len,1,"equality work length overflow"));ctx->work=(SvEqWork*)sv_xrealloc(ctx->work,sv_size_mul_or_fail(sizeof(SvEqWork),ctx->work_cap,"equality worklist overflow"));}
    ctx->work[ctx->work_len++]=(SvEqWork){a,b};
}
static bool sv_key_equal(SlugValue a,SlugValue b){return sv_scalar_equal(a,b);}
static bool sv_map_find(SlugMap *m,SlugValue key,size_t *out){for(size_t i=0;i<m->len;i++)if(sv_key_equal(m->keys[i],key)){*out=i;return true;}return false;}
static bool sv_equal(SlugValue first_a,SlugValue first_b){
    SvEqCtx ctx={0}; bool ok=true; sv_eq_push(&ctx,first_a,first_b);
    while(ctx.work_len&&ok){
        SvEqWork w=ctx.work[--ctx.work_len];SlugValue a=w.a,b=w.b;
        if(sv_numeric_tag(a.tag)&&sv_numeric_tag(b.tag)){if(sv_numeric_compare(a,b)!=0)ok=false;continue;}
        if(a.tag!=b.tag){ok=false;continue;}
        switch(a.tag){
            case SV_NULL:case SV_BOOL:case SV_INT:case SV_UINT:case SV_FLOAT:case SV_STRING:case SV_BYTES:case SV_SOCKET:case SV_FILE:case SV_SURFACE:case SV_WINDOW:case SV_AUDIO:case SV_DEVICE:case SV_CALLABLE:case SV_DEFAULT:
                if(!sv_scalar_equal(a,b))ok=false;break;
            case SV_LIST:
                if(a.as.list==b.as.list)break;if(!a.as.list||!b.as.list||a.as.list->len!=b.as.list->len){ok=false;break;}if(sv_eq_seen_or_add(&ctx,SV_LIST,a.as.list,b.as.list))break;
                for(size_t i=a.as.list->len;i>0;i--)sv_eq_push(&ctx,a.as.list->items[i-1],b.as.list->items[i-1]);break;
            case SV_MAP:
                if(a.as.map==b.as.map)break;if(!a.as.map||!b.as.map||a.as.map->len!=b.as.map->len){ok=false;break;}if(sv_eq_seen_or_add(&ctx,SV_MAP,a.as.map,b.as.map))break;
                for(size_t i=0;i<a.as.map->len;i++){size_t j;if(!sv_map_find(b.as.map,a.as.map->keys[i],&j)){ok=false;break;}sv_eq_push(&ctx,a.as.map->vals[i],b.as.map->vals[j]);}break;
            case SV_OBJECT:
                if(a.as.obj==b.as.obj)break;if(!a.as.obj||!b.as.obj||a.as.obj->class_id!=b.as.obj->class_id||a.as.obj->len!=b.as.obj->len){ok=false;break;}if(sv_eq_seen_or_add(&ctx,SV_OBJECT,a.as.obj,b.as.obj))break;
                for(size_t i=0;i<a.as.obj->len;i++){size_t found=SIZE_MAX;for(size_t j=0;j<b.as.obj->len;j++)if(strcmp(a.as.obj->names[i],b.as.obj->names[j])==0){found=j;break;}if(found==SIZE_MAX){ok=false;break;}sv_eq_push(&ctx,a.as.obj->values[i],b.as.obj->values[found]);}break;
            case SV_ERROR:
                if(a.as.err==b.as.err)break;if(!a.as.err||!b.as.err){ok=false;break;}if(sv_eq_seen_or_add(&ctx,SV_ERROR,a.as.err,b.as.err))break;
                sv_eq_push(&ctx,a.as.err->suppressed,b.as.err->suppressed);sv_eq_push(&ctx,a.as.err->cause,b.as.err->cause);sv_eq_push(&ctx,a.as.err->payload,b.as.err->payload);sv_eq_push(&ctx,a.as.err->message,b.as.err->message);sv_eq_push(&ctx,a.as.err->kind,b.as.err->kind);break;
        }
    }
    free(ctx.seen);free(ctx.work);return ok;
}
static bool sv_identical(SlugValue a, SlugValue b){
    if(a.tag!=b.tag)return false;
    if(a.tag==SV_STRING||a.tag==SV_BYTES||a.tag==SV_NULL||a.tag==SV_BOOL||a.tag==SV_INT||a.tag==SV_UINT||a.tag==SV_FLOAT)return sv_equal(a,b);
    if(a.tag==SV_SOCKET)return a.as.sock==b.as.sock;if(a.tag==SV_FILE)return a.as.file==b.as.file;if(a.tag==SV_SURFACE)return a.as.surface==b.as.surface;if(a.tag==SV_WINDOW)return a.as.window==b.as.window;if(a.tag==SV_AUDIO)return a.as.audio==b.as.audio;if(a.tag==SV_DEVICE)return a.as.device==b.as.device;if(a.tag==SV_LIST)return a.as.list==b.as.list;if(a.tag==SV_MAP)return a.as.map==b.as.map;if(a.tag==SV_OBJECT)return a.as.obj==b.as.obj;if(a.tag==SV_CALLABLE)return a.as.closure==b.as.closure;if(a.tag==SV_ERROR)return a.as.err==b.as.err;return true;
}
static int sv_compare(SlugValue a,SlugValue b){
    if(sv_numeric_tag(a.tag)&&sv_numeric_tag(b.tag))return sv_numeric_compare(a,b);
    if(a.tag==SV_STRING&&b.tag==SV_STRING){size_t an=a.as.s?a.as.s->len:0,bn=b.as.s?b.as.s->len:0,n=an<bn?an:bn;int c=n?memcmp(a.as.s->data,b.as.s->data,n):0;if(c)return(c>0)-(c<0);return(an>bn)-(an<bn);}
    if(a.tag==SV_BYTES&&b.tag==SV_BYTES){size_t an=a.as.bytes?a.as.bytes->len:0,bn=b.as.bytes?b.as.bytes->len:0,n=an<bn?an:bn;int c=n?memcmp(a.as.bytes->data,b.as.bytes->data,n):0;if(c)return(c>0)-(c<0);return(an>bn)-(an<bn);}
    sv_fail_kind("type","incomparable values");return 0;
}

static SlugList *sv_list_new_raw(bool frozen,size_t n){
    SlugList *l=(SlugList*)sv_heap_alloc(sizeof(SlugList),SH_LIST);l->frozen=frozen;l->len=n;l->cap=n;l->items=n?(SlugValue*)sv_xmalloc(sv_size_mul_or_fail(sizeof(SlugValue),n,"list allocation overflow")):NULL;return l;
}
static SlugValue sv_list_empty(bool frozen){return sv_list_value(sv_list_new_raw(frozen,0));}
static SlugValue sv_list_from(SlugValue *items,size_t n,bool frozen){SlugList *l=sv_list_new_raw(frozen,n);if(n)memcpy(l->items,items,sv_size_mul_or_fail(sizeof(SlugValue),n,"list copy overflow"));return sv_list_value(l);}
static SlugValue sv_list_from_args(SlugValue *items,size_t n){return n?sv_list_from(items,n,false):sv_list_empty(false);}
static SlugValue sv_error_supersede(SlugValue newer,SlugValue prior){
    newer=sv_wrap_error(newer);prior=sv_wrap_error(prior);SlugErrorValue *e=newer.as.err;
    if(e->cause.tag==SV_NULL)return sv_error_new((const char*)sv_str_data(e->kind),(const char*)sv_str_data(e->message),e->payload,prior,e->suppressed);
    size_t n=e->suppressed.as.list?e->suppressed.as.list->len:0;size_t z=sv_size_add_or_fail(n,1,"suppressed error list overflow");SlugValue *items=(SlugValue*)sv_xmalloc(sv_size_mul_or_fail(sizeof(SlugValue),z,"suppressed error list overflow"));
    if(n)memcpy(items,e->suppressed.as.list->items,sv_size_mul_or_fail(sizeof(SlugValue),n,"suppressed error list overflow"));items[n]=prior;SlugValue sup=sv_list_from(items,z,true);free(items);
    return sv_error_new((const char*)sv_str_data(e->kind),(const char*)sv_str_data(e->message),e->payload,e->cause,sup);
}
static void sv_list_append(SlugList *l,SlugValue v){if(l->frozen)sv_fail_kind("immutable","cannot mutate frozen list");if(l->len==l->cap){size_t cap=sv_grow_capacity(l->cap,sv_size_add_or_fail(l->len,1,"list length overflow"));l->items=(SlugValue*)sv_xrealloc(l->items,sv_size_mul_or_fail(sizeof(SlugValue),cap,"list capacity overflow"));l->cap=cap;}l->items[l->len++]=v;}
static size_t sv_index_position(SlugValue iv,size_t n);
static SlugList *sv_require_mutable_list_value(SlugValue v,const char *op){
    if(v.tag!=SV_LIST||!v.as.list)sv_fail_kind("type",op);
    if(v.as.list->frozen)sv_fail_kind("immutable","cannot mutate frozen list");
    return v.as.list;
}
static size_t sv_list_insert_position(SlugValue iv,size_t n){
    if(iv.tag==SV_UINT){if(iv.as.u>(uint64_t)SIZE_MAX||(size_t)iv.as.u>n)sv_fail_kind("index","list insertion index out of range");return(size_t)iv.as.u;}
    if(iv.tag!=SV_INT)sv_fail_kind("type","list insertion index must be an integer");
    if(iv.as.i>=0){uint64_t u=(uint64_t)iv.as.i;if(u>(uint64_t)SIZE_MAX||(size_t)u>n)sv_fail_kind("index","list insertion index out of range");return(size_t)u;}
    uint64_t mag=(uint64_t)(-(iv.as.i+1))+1;if(mag>(uint64_t)n)sv_fail_kind("index","list insertion index out of range");return n-(size_t)mag;
}
static SlugValue sv_list_api_append(SlugValue lv,SlugValue value){SlugList *l=sv_require_mutable_list_value(lv,"LI.ap requires list");sv_list_append(l,value);return lv;}
static SlugValue sv_list_api_insert(SlugValue lv,SlugValue index,SlugValue value){
    SlugList *l=sv_require_mutable_list_value(lv,"LI.ip requires list");size_t i=sv_list_insert_position(index,l->len);
    if(l->len==l->cap){size_t cap=sv_grow_capacity(l->cap,sv_size_add_or_fail(l->len,1,"list length overflow"));l->items=(SlugValue*)sv_xrealloc(l->items,sv_size_mul_or_fail(sizeof(SlugValue),cap,"list capacity overflow"));l->cap=cap;}
    if(i<l->len)memmove(l->items+i+1,l->items+i,sv_size_mul_or_fail(sizeof(SlugValue),l->len-i,"list insert move overflow"));l->items[i]=value;l->len++;return lv;
}
static SlugValue sv_list_api_remove(SlugValue lv,SlugValue value){
    SlugList *l=sv_require_mutable_list_value(lv,"LI.rm requires list");
    for(size_t i=0;i<l->len;i++)if(sv_equal(l->items[i],value)){if(i+1<l->len)memmove(l->items+i,l->items+i+1,sv_size_mul_or_fail(sizeof(SlugValue),l->len-i-1,"list remove move overflow"));l->len--;if(l->items)l->items[l->len]=sv_null();return sv_bool(true);}
    return sv_bool(false);
}
static SlugValue sv_list_api_pop(SlugValue lv,bool has_index,SlugValue index){
    SlugList *l=sv_require_mutable_list_value(lv,"LI.pp requires list");if(!l->len)sv_fail_kind("index","cannot pop from empty list");size_t i=has_index?sv_index_position(index,l->len):l->len-1;SlugValue out=l->items[i];
    if(i+1<l->len)memmove(l->items+i,l->items+i+1,sv_size_mul_or_fail(sizeof(SlugValue),l->len-i-1,"list pop move overflow"));l->len--;l->items[l->len]=sv_null();return out;
}
static bool sv_stable_map_key(SlugValue k){return k.tag==SV_NULL||k.tag==SV_BOOL||k.tag==SV_INT||k.tag==SV_UINT||k.tag==SV_FLOAT||k.tag==SV_STRING||k.tag==SV_BYTES;}
static SlugMap *sv_map_new_raw(bool frozen,size_t n){SlugMap *m=(SlugMap*)sv_heap_alloc(sizeof(SlugMap),SH_MAP);m->frozen=frozen;m->len=0;m->cap=n;m->keys=n?(SlugValue*)sv_xmalloc(sv_size_mul_or_fail(sizeof(SlugValue),n,"map allocation overflow")):NULL;m->vals=n?(SlugValue*)sv_xmalloc(sv_size_mul_or_fail(sizeof(SlugValue),n,"map allocation overflow")):NULL;return m;}
static void sv_map_reserve(SlugMap *m,size_t need){if(need<=m->cap)return;size_t cap=sv_grow_capacity(m->cap,need);size_t bytes=sv_size_mul_or_fail(sizeof(SlugValue),cap,"map capacity overflow");m->keys=(SlugValue*)sv_xrealloc(m->keys,bytes);m->vals=(SlugValue*)sv_xrealloc(m->vals,bytes);m->cap=cap;}
static void sv_map_put_raw(SlugMap *m,SlugValue k,SlugValue v){if(!sv_stable_map_key(k))sv_fail_kind("key","unstable map key type");size_t i;if(sv_map_find(m,k,&i)){m->vals[i]=v;return;}sv_map_reserve(m,sv_size_add_or_fail(m->len,1,"map length overflow"));m->keys[m->len]=k;m->vals[m->len]=v;m->len++;}
static SlugValue sv_map_empty(bool frozen){return sv_map_value(sv_map_new_raw(frozen,0));}
static SlugValue sv_map_from(SlugValue *flat,size_t pairs,bool frozen){SlugMap *m=sv_map_new_raw(false,pairs);for(size_t i=0;i<pairs;i++){SlugValue k=flat[i*2];if(!sv_stable_map_key(k))sv_fail_kind("key","unstable map key type");size_t prior;if(sv_map_find(m,k,&prior))sv_fail_kind("key","duplicate map literal key");sv_map_put_raw(m,k,flat[i*2+1]);}m->frozen=frozen;return sv_map_value(m);}
static SlugValue sv_eval_list_literal(bool frozen){size_t n=sv_eval_count();SlugValue v=sv_list_from(sv_eval_argv(0),n,frozen);sv_eval_finish();return v;}
static SlugValue sv_eval_map_literal(bool frozen){size_t n=sv_eval_count();if(n%2)sv_fail("map evaluation arity");SlugValue v=sv_map_from(sv_eval_argv(0),n/2,frozen);sv_eval_finish();return v;}

static SlugObject *sv_object_new(int class_id,const char *class_name){
    SlugObject *o=(SlugObject*)sv_heap_alloc(sizeof(SlugObject),SH_OBJECT);o->class_id=class_id;o->class_name=class_name;o->destroyed=false;o->len=0;o->cap=0;o->names=NULL;o->values=NULL;o->immutable=NULL;return o;
}
static bool sv_object_find(SlugObject *o,const char *name,size_t *out){for(size_t i=0;i<o->len;i++)if(strcmp(o->names[i],name)==0){*out=i;return true;}return false;}
static void sv_object_reserve(SlugObject *o,size_t need){
    if(need<=o->cap)return;size_t cap=sv_grow_capacity(o->cap,need);
    o->names=(char**)sv_xrealloc(o->names,sv_size_mul_or_fail(sizeof(char*),cap,"object capacity overflow"));o->values=(SlugValue*)sv_xrealloc(o->values,sv_size_mul_or_fail(sizeof(SlugValue),cap,"object capacity overflow"));o->immutable=(bool*)sv_xrealloc(o->immutable,sv_size_mul_or_fail(sizeof(bool),cap,"object capacity overflow"));o->cap=cap;
}
static SlugObject *sv_as_object(SlugValue v){if(v.tag!=SV_OBJECT||!v.as.obj)sv_fail_kind("type","object value required");return v.as.obj;}
static SlugValue sv_object_get(SlugValue ov,const char *name){
    if(ov.tag==SV_ERROR&&ov.as.err){if(strcmp(name,"kind")==0)return ov.as.err->kind;if(strcmp(name,"message")==0)return ov.as.err->message;if(strcmp(name,"payload")==0)return ov.as.err->payload;if(strcmp(name,"cause")==0)return ov.as.err->cause;if(strcmp(name,"suppressed")==0)return ov.as.err->suppressed;sv_fail_kind("key","unknown error field");}
    SlugObject *o=sv_as_object(ov);size_t i;if(!sv_object_find(o,name,&i))sv_fail_kind("key","unknown object field");return o->values[i];
}
static SlugValue sv_object_set(SlugValue ov,const char *name,SlugValue value,bool define,bool immutable,bool initialization){
    if(ov.tag==SV_ERROR)sv_fail_kind("immutable","error values are immutable");
    SlugObject *o=sv_as_object(ov);size_t i;bool found=sv_object_find(o,name,&i);
    if(!found){if(!define)sv_fail_kind("key","unknown object field");sv_object_reserve(o,sv_size_add_or_fail(o->len,1,"object length overflow"));i=o->len++;o->names[i]=sv_dup(name);o->values[i]=value;o->immutable[i]=immutable;return value;}
    if(o->immutable[i]&&!initialization)sv_fail_kind("immutable","cannot assign immutable object field");o->values[i]=value;if(immutable)o->immutable[i]=true;return value;
}

static SlugValue sv_eval_object_get(const char *name){if(sv_eval_count()!=1)sv_fail("member evaluation arity");SlugValue v=sv_object_get(sv_eval_argv(0)[0],name);sv_eval_finish();return v;}
static SlugValue sv_eval_object_set(const char *name,bool define,bool immutable,bool initialization){if(sv_eval_count()!=2)sv_fail("member assignment evaluation arity");SlugValue *a=sv_eval_argv(0);SlugValue v=sv_object_set(a[0],name,a[1],define,immutable,initialization);sv_eval_finish();return v;}

/* v0.1.3 managed heap: lexical cells are roots while their scope is active, closures
   keep captured cells reachable, and graph tracing reclaims both acyclic and cyclic
   values.  No ownership syntax leaks into SLUG source. */
static SvHeap *sv_value_heap(SlugValue v){
    switch(v.tag){
        case SV_STRING:return v.as.s?&v.as.s->heap:NULL;
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
static void sv_mark_push(SvMarkStack *st,SvHeap *h){if(!h||h->marked)return;if(st->len==st->cap){st->cap=sv_grow_capacity(st->cap,sv_size_add_or_fail(st->len,1,"GC mark length overflow"));st->items=(SvHeap**)sv_xrealloc(st->items,sv_size_mul_or_fail(sizeof(SvHeap*),st->cap,"GC mark stack overflow"));}st->items[st->len++]=h;}
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
    for(SlugScopeState *f=sv_scope_top;f;f=f->prev)for(size_t i=0;i<f->len;i++){SlugCell *c=f->cells[i];if(c->heap_owned)sv_mark_push(&st,&c->heap);else sv_mark_value(&st,c->value);}
    for(size_t i=0;i<sv_root_slots_len;i++)if(sv_root_slots[i])sv_mark_value(&st,*sv_root_slots[i]);
    for(size_t i=0;i<sv_temp_roots_len;i++)sv_mark_value(&st,sv_temp_roots[i]);
    for(SlugExcState *f=sv_exc_top;f;f=f->prev)sv_mark_value(&st,f->error);
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
    if(setjmp(SV_EXC_ENV(&isolated))==0){
        sv_object_destructor(o);sv_exc_pop(&isolated);sv_temp_root_pop(root);return true;
    }
    SlugValue err=sv_exc_error(&isolated);sv_exc_pop(&isolated);sv_temp_root_pop(root);
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
static bool sv_runtime_shutdown(void){
    if(sv_runtime_stopped)return false;sv_gc_running=true;bool failed=false;
    if(sv_object_destructor){for(SvHeap *h=sv_heap_head;h;h=h->next)if(h->kind==SH_OBJECT&&!((SlugObject*)h)->destroyed){SlugValue ferr=sv_null();if(!sv_run_finalizer((SlugObject*)h,true,&ferr)){failed=true;fputs("SLUG finalizer error during shutdown: ",stderr);sv_report_uncaught(ferr);}}}
    while(sv_heap_head)sv_heap_free_node(sv_heap_head);
#ifdef _WIN32
    WSACleanup();
#endif
    while(sv_scope_top){SlugScopeState *f=sv_scope_top;sv_scope_top=f->prev;if(f->owner)f->owner->state=NULL;free(f->cells);free(f);}
    free(sv_root_slots);sv_root_slots=NULL;sv_root_slots_len=sv_root_slots_cap=0;free(sv_temp_roots);sv_temp_roots=NULL;sv_temp_roots_len=sv_temp_roots_cap=0;free(sv_eval_marks);sv_eval_marks=NULL;sv_eval_marks_len=sv_eval_marks_cap=0;while(sv_exc_top){SlugExcState *e=sv_exc_top;sv_exc_top=e->prev;if(e->owner)e->owner->state=NULL;free(e);}
    sv_runtime_stopped=true;sv_gc_running=false;return failed;
}

static void sv_runtime_heap_report(void){const char *report=getenv("SLUG_HEAP_REPORT");if(report&&report[0]&&strcmp(report,"0")!=0)fprintf(stderr,"SLUG heap: allocated=%zu freed=%zu live=%zu peak=%zu collections=%zu\n",sv_heap_allocated,sv_heap_freed,sv_heap_allocated-sv_heap_freed,sv_heap_peak,sv_gc_collections);}
static void sv_runtime_atexit(void){if(!sv_runtime_stopped)(void)sv_runtime_shutdown();sv_runtime_heap_report();}
static void sv_runtime_init(void){
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);SetConsoleCP(CP_UTF8);WSADATA wsa;if(WSAStartup(MAKEWORD(2,2),&wsa)!=0){fputs("SLUG runtime: Winsock initialization failed\n",stderr);exit(65);}
#endif
    atexit(sv_runtime_atexit);
}

typedef struct { unsigned char *p; size_t n,cap; } SvBuf;
static void sb_init(SvBuf *b){b->cap=64;b->n=0;b->p=(unsigned char*)sv_xmalloc(b->cap);b->p[0]=0;}
static void sb_need(SvBuf *b,size_t add){size_t need=sv_size_add_or_fail(sv_size_add_or_fail(b->n,add,"buffer size overflow"),1,"buffer size overflow");if(need<=b->cap)return;b->cap=sv_grow_capacity(b->cap,need);b->p=(unsigned char*)sv_xrealloc(b->p,b->cap);}
static void sb_add_n(SvBuf *b,const void *p,size_t n){if(!n)return;sb_need(b,n);memcpy(b->p+b->n,p,n);b->n+=n;b->p[b->n]=0;}
static void sb_add(SvBuf *b,const char *s){sb_add_n(b,s,strlen(s));}
static void sb_ch(SvBuf *b,unsigned char c){sb_need(b,1);b->p[b->n++]=c;b->p[b->n]=0;}
static void sb_u64(SvBuf *b,uint64_t x){char t[32];int n=snprintf(t,sizeof(t),"%" PRIu64,x);if(n>0)sb_add_n(b,t,(size_t)n);}
static void sb_i64(SvBuf *b,int64_t x){char t[32];int n=snprintf(t,sizeof(t),"%" PRId64,x);if(n>0)sb_add_n(b,t,(size_t)n);}
static void sb_f64(SvBuf *b,double x){char t[64];int n=snprintf(t,sizeof(t),"%.17g",x);if(n>0)sb_add_n(b,t,(size_t)n);}
static void sb_quote_string(SvBuf *b,SlugString *s){sb_ch(b,'\'');if(s){for(size_t i=0;i<s->len;i++){unsigned char c=s->data[i];switch(c){case '\\':sb_add(b,"\\\\");break;case '\'':sb_add(b,"\\\'");break;case '\n':sb_add(b,"\\n");break;case '\r':sb_add(b,"\\r");break;case '\t':sb_add(b,"\\t");break;case 0:sb_add(b,"\\0");break;default:sb_ch(b,c);break;}}}sb_ch(b,'\'');}

typedef enum {SFT_VALUE,SFT_TEXT,SFT_CHAR,SFT_LEAVE} SvFmtKind;
typedef struct {SvFmtKind kind;SlugValue value;const char *text;unsigned char ch;SlugTag tag;const void *ptr;bool nested;} SvFmtTask;
typedef struct {SvFmtTask *p;size_t n,cap;} SvFmtTasks;
typedef struct {SlugTag tag;const void *ptr;} SvActiveItem;
typedef struct {SvActiveItem *p;size_t n,cap;} SvActive;
static void sft_push(SvFmtTasks *q,SvFmtTask t){if(q->n==q->cap){q->cap=sv_grow_capacity(q->cap,sv_size_add_or_fail(q->n,1,"format worklist length overflow"));q->p=(SvFmtTask*)sv_xrealloc(q->p,sv_size_mul_or_fail(sizeof(SvFmtTask),q->cap,"format worklist overflow"));}q->p[q->n++]=t;}
static void sft_value(SvFmtTasks *q,SlugValue v,bool nested){SvFmtTask t={0};t.kind=SFT_VALUE;t.value=v;t.nested=nested;sft_push(q,t);}
static void sft_text(SvFmtTasks *q,const char *x){SvFmtTask t={0};t.kind=SFT_TEXT;t.text=x;sft_push(q,t);}
static void sft_char(SvFmtTasks *q,unsigned char x){SvFmtTask t={0};t.kind=SFT_CHAR;t.ch=x;sft_push(q,t);}
static void sft_leave(SvFmtTasks *q,SlugTag tag,const void *ptr){SvFmtTask t={0};t.kind=SFT_LEAVE;t.tag=tag;t.ptr=ptr;sft_push(q,t);}
static bool sva_contains(SvActive *a,SlugTag tag,const void *ptr){for(size_t i=0;i<a->n;i++)if(a->p[i].tag==tag&&a->p[i].ptr==ptr)return true;return false;}
static void sva_push(SvActive *a,SlugTag tag,const void *ptr){if(a->n==a->cap){a->cap=sv_grow_capacity(a->cap,sv_size_add_or_fail(a->n,1,"format active length overflow"));a->p=(SvActiveItem*)sv_xrealloc(a->p,sv_size_mul_or_fail(sizeof(SvActiveItem),a->cap,"format active stack overflow"));}a->p[a->n++]=(SvActiveItem){tag,ptr};}
static void sva_leave(SvActive *a,SlugTag tag,const void *ptr){if(!a->n||a->p[a->n-1].tag!=tag||a->p[a->n-1].ptr!=ptr)sv_fail("format active stack corruption");a->n--;}
static void sv_format_into(SvBuf *b,SlugValue root){
    SvFmtTasks q={0};SvActive active={0};sft_value(&q,root,false);
    while(q.n){SvFmtTask t=q.p[--q.n];if(t.kind==SFT_TEXT){sb_add(b,t.text);continue;}if(t.kind==SFT_CHAR){sb_ch(b,t.ch);continue;}if(t.kind==SFT_LEAVE){sva_leave(&active,t.tag,t.ptr);continue;}SlugValue v=t.value;
        switch(v.tag){
            case SV_NULL:sb_add(b,"nn");break;case SV_BOOL:sb_add(b,v.as.b?"true":"false");break;case SV_INT:sb_i64(b,v.as.i);break;case SV_UINT:sb_u64(b,v.as.u);break;case SV_FLOAT:sb_f64(b,v.as.f);break;
            case SV_STRING:if(t.nested)sb_quote_string(b,v.as.s);else if(v.as.s)sb_add_n(b,v.as.s->data,v.as.s->len);break;
            case SV_BYTES:{sb_add(b,"0x");static const char hx[]="0123456789ABCDEF";if(v.as.bytes)for(size_t i=0;i<v.as.bytes->len;i++){unsigned char x=v.as.bytes->data[i];sb_ch(b,(unsigned char)hx[x>>4]);sb_ch(b,(unsigned char)hx[x&15]);}break;}
            case SV_SOCKET:sb_add(b,v.as.sock&&v.as.sock->closed?"socket(closed)":"socket");break;case SV_FILE:sb_add(b,v.as.file&&v.as.file->closed?"file(closed)":"file");break;case SV_SURFACE:sb_add(b,"surface");break;case SV_WINDOW:sb_add(b,v.as.window&&v.as.window->closed?"window(closed)":"window");break;case SV_AUDIO:sb_add(b,v.as.audio&&v.as.audio->closed?"audio(closed)":"audio");break;case SV_DEVICE:sb_add(b,v.as.device&&v.as.device->closed?"device(closed)":"device");break;
            case SV_CALLABLE:sb_add(b,"callable");break;case SV_DEFAULT:sb_add(b,"xx");break;
            case SV_OBJECT:sb_add(b,v.as.obj&&v.as.obj->class_name?v.as.obj->class_name:"object");break;
            case SV_LIST:{SlugList *x=v.as.list;if(!x){sb_add(b,"[]");break;}if(sva_contains(&active,SV_LIST,x)){sb_add(b,"<cycle>");break;}sva_push(&active,SV_LIST,x);sb_ch(b,'[');sft_leave(&q,SV_LIST,x);sft_char(&q,']');for(size_t i=x->len;i>0;i--){if(i<x->len)sft_char(&q,',');sft_value(&q,x->items[i-1],true);}break;}
            case SV_MAP:{SlugMap *x=v.as.map;if(!x){sb_add(b,"[:]");break;}if(sva_contains(&active,SV_MAP,x)){sb_add(b,"<cycle>");break;}sva_push(&active,SV_MAP,x);sb_ch(b,'[');sft_leave(&q,SV_MAP,x);sft_char(&q,']');for(size_t i=x->len;i>0;i--){if(i<x->len)sft_char(&q,',');sft_value(&q,x->vals[i-1],true);sft_char(&q,':');sft_value(&q,x->keys[i-1],true);}break;}
            case SV_ERROR:{SlugErrorValue *x=v.as.err;if(!x){sb_add(b,"ER()");break;}if(sva_contains(&active,SV_ERROR,x)){sb_add(b,"<cycle>");break;}sva_push(&active,SV_ERROR,x);sb_add(b,"ER(");sft_leave(&q,SV_ERROR,x);sft_char(&q,')');sft_value(&q,x->suppressed,true);sft_text(&q,", suppressed=");sft_value(&q,x->cause,true);sft_text(&q,", cause=");sft_value(&q,x->payload,true);sft_text(&q,", payload=");sft_value(&q,x->message,true);sft_text(&q,", message=");sft_value(&q,x->kind,true);sft_text(&q,"kind=");break;}
        }
    }
    free(q.p);free(active.p);
}
static char *sv_to_cstr(SlugValue v){SvBuf b;sb_init(&b);sv_format_into(&b,v);return (char*)b.p;}
static void sv_report_uncaught(SlugValue e){SvBuf b;sb_init(&b);sv_format_into(&b,e);fwrite(b.p,1,b.n,stderr);fputc('\n',stderr);free(b.p);}
static void sv_fail_kind(const char *kind,const char *msg){sv_raise(sv_error_new(kind,msg,sv_null(),sv_null(),sv_null()));}
static void sv_fail(const char *msg){sv_fail_kind("state",msg);}

static SlugValue sv_add(SlugValue a,SlugValue b){
    if(a.tag==SV_BYTES||b.tag==SV_BYTES){if(a.tag!=SV_BYTES||b.tag!=SV_BYTES)sv_fail_kind("type","bytes concatenation requires bytes + bytes");size_t n=sv_size_add_or_fail(a.as.bytes->len,b.as.bytes->len,"bytes size overflow");unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;if(a.as.bytes->len)memcpy(p,a.as.bytes->data,a.as.bytes->len);if(b.as.bytes->len)memcpy(p+a.as.bytes->len,b.as.bytes->data,b.as.bytes->len);SlugValue v=sv_bytes(p,n);free(p);return v;}
    if(a.tag==SV_STRING||b.tag==SV_STRING){if(a.tag!=SV_STRING||b.tag!=SV_STRING)sv_fail_kind("type","string concatenation requires string + string");size_t an=sv_str_len(a),bn=sv_str_len(b),n=sv_size_add_or_fail(an,bn,"string size overflow");unsigned char *buf=n?(unsigned char*)sv_xmalloc(n):NULL;if(an)memcpy(buf,sv_str_data(a),an);if(bn)memcpy(buf+an,sv_str_data(b),bn);SlugValue v=sv_string_n(buf,n);free(buf);return v;}
    if(!sv_numeric_tag(a.tag)||!sv_numeric_tag(b.tag))sv_fail_kind("type","numeric addition requires numeric operands");
    if(a.tag==SV_FLOAT||b.tag==SV_FLOAT)return sv_float(sv_num(a)+sv_num(b));return sv_wadd(sv_wint(a),sv_wint(b));
}
static SlugValue sv_sub(SlugValue a,SlugValue b){if(!sv_numeric_tag(a.tag)||!sv_numeric_tag(b.tag))sv_fail_kind("type","numeric subtraction requires numeric operands");if(a.tag==SV_FLOAT||b.tag==SV_FLOAT)return sv_float(sv_num(a)-sv_num(b));return sv_wsub(sv_wint(a),sv_wint(b));}
static SlugValue sv_mul(SlugValue a,SlugValue b){if(!sv_numeric_tag(a.tag)||!sv_numeric_tag(b.tag))sv_fail_kind("type","numeric multiplication requires numeric operands");if(a.tag==SV_FLOAT||b.tag==SV_FLOAT)return sv_float(sv_num(a)*sv_num(b));return sv_wmul(sv_wint(a),sv_wint(b));}
static SlugValue sv_div(SlugValue a,SlugValue b){if(!sv_numeric_tag(a.tag)||!sv_numeric_tag(b.tag))sv_fail_kind("type","numeric division requires numeric operands");double d=sv_num(b);if(d==0.0)sv_fail_kind("divide","division by zero");return sv_float(sv_num(a)/d);}
static SlugValue sv_idiv(SlugValue a,SlugValue b){SvWideInt x=sv_wint(a),y=sv_wint(b);if(y.mag==0)sv_fail_kind("divide","integer division by zero");uint64_t q=x.mag/y.mag;bool neg=(x.neg!=y.neg)&&q!=0;bool pref=(x.prefer_unsigned||y.prefer_unsigned)&&!neg;return sv_wint_value(neg,q,pref);}
static SlugValue sv_mod(SlugValue a,SlugValue b){SvWideInt x=sv_wint(a),y=sv_wint(b);if(y.mag==0)sv_fail_kind("divide","remainder by zero");uint64_t r=x.mag%y.mag;bool neg=x.neg&&r!=0;bool pref=(x.prefer_unsigned||y.prefer_unsigned)&&!neg;return sv_wint_value(neg,r,pref);}
static SlugValue sv_pow(SlugValue a,SlugValue b){
    if(a.tag==SV_FLOAT||b.tag==SV_FLOAT){double x=sv_num(a),y=sv_num(b);if(x==0.0&&y<0.0)sv_fail("zero to negative exponent");if(x==0.0&&y==0.0)return sv_int(1);return sv_float(pow(x,y));}
    SvWideInt e=sv_wint(b);if(e.neg){double x=sv_num(a),y=-(double)e.mag;if(x==0.0)sv_fail("zero to negative exponent");return sv_float(pow(x,y));}
    if((a.tag==SV_INT&&a.as.i==0)||(a.tag==SV_UINT&&a.as.u==0)){if(e.mag==0)return sv_int(1);}
    SlugValue r=sv_int(1),base=a;uint64_t n=e.mag;while(n){if(n&1)r=sv_mul(r,base);n>>=1;if(n)base=sv_mul(base,base);}return r;
}
static SlugValue sv_neg(SlugValue a){if(a.tag==SV_FLOAT)return sv_float(-a.as.f);SvWideInt x=sv_wint(a);x.neg=!x.neg;return sv_wint_value(x.neg,x.mag,false);}
static bool sv_ascii_space(unsigned char c){return c==' '||c=='\t'||c=='\n'||c=='\r'||c=='\f'||c=='\v';}
static void sv_trim_ascii_n(const char *s,size_t n,const char **start,const char **end){const char *a=s,*b=s+n;while(a<b&&sv_ascii_space((unsigned char)*a))a++;while(b>a&&sv_ascii_space((unsigned char)b[-1]))b--;*start=a;*end=b;}
static bool sv_parse_dec_wide_n(const char *s,size_t n,bool allow_negative,SvWideInt *out){
    const char *p,*e;sv_trim_ascii_n(s,n,&p,&e);if(p==e)return false;bool neg=false;if(*p=='+'||*p=='-'){neg=*p=='-';p++;if(p==e)return false;}if(neg&&!allow_negative)return false;
    uint64_t mag=0;for(;p<e;p++){unsigned char c=(unsigned char)*p;if(c<'0'||c>'9')return false;unsigned d=(unsigned)(c-'0');if(mag>(UINT64_MAX-d)/10)return false;mag=mag*10+d;}
    out->neg=neg&&mag!=0;out->mag=mag;out->prefer_unsigned=!out->neg;return true;
}
static bool sv_valid_decimal_float_span(const char *p,const char *e){
    if(p==e)return false;if(*p=='+'||*p=='-'){p++;if(p==e)return false;}bool before=false,after=false;while(p<e&&*p>='0'&&*p<='9'){before=true;p++;}
    if(p<e&&*p=='.'){p++;while(p<e&&*p>='0'&&*p<='9'){after=true;p++;}}if(!before&&!after)return false;
    if(p<e&&(*p=='e'||*p=='E')){p++;if(p<e&&(*p=='+'||*p=='-'))p++;const char *q=p;while(p<e&&*p>='0'&&*p<='9')p++;if(p==q)return false;}return p==e;
}
static bool sv_parse_dec_float_n(const char *s,size_t n,double *out){
    const char *a,*e;sv_trim_ascii_n(s,n,&a,&e);if(!sv_valid_decimal_float_span(a,e))return false;size_t m=(size_t)(e-a);char *buf=sv_dup_n(a,m);errno=0;char *z=NULL;double v=strtod(buf,&z);bool ok=z==buf+m&&errno!=ERANGE&&isfinite(v);free(buf);if(!ok)return false;*out=v;return true;
}
static bool sv_text_to_i64_n(const char *s,size_t n,int64_t *out){SvWideInt w;if(!sv_parse_dec_wide_n(s,n,true,&w))return false;if((!w.neg&&w.mag>(uint64_t)INT64_MAX)||(w.neg&&w.mag>UINT64_C(9223372036854775808)))return false;if(w.neg){if(w.mag==UINT64_C(9223372036854775808))*out=INT64_MIN;else *out=-(int64_t)w.mag;}else *out=(int64_t)w.mag;return true;}
static bool sv_text_to_u64_n(const char *s,size_t n,uint64_t *out){SvWideInt w;if(!sv_parse_dec_wide_n(s,n,false,&w))return false;*out=w.mag;return true;}
static bool sv_text_to_float_n(const char *s,size_t n,double *out){return sv_parse_dec_float_n(s,n,out);}
static bool sv_text_to_i64(const char *s,int64_t *out){return sv_text_to_i64_n(s?s:"",s?strlen(s):0,out);}
static bool sv_text_to_u64(const char *s,uint64_t *out){return sv_text_to_u64_n(s?s:"",s?strlen(s):0,out);}
static bool sv_text_to_float(const char *s,double *out){return sv_text_to_float_n(s?s:"",s?strlen(s):0,out);}
static bool sv_string_has_nul(SlugValue v){return v.tag==SV_STRING&&v.as.s&&memchr(v.as.s->data,0,v.as.s->len)!=NULL;}
static const char *sv_string_cstr_boundary(SlugValue v,const char *what){if(v.tag!=SV_STRING)sv_fail_kind("type",what);if(sv_string_has_nul(v))sv_fail_kind("encoding","embedded NUL is not valid in terminated host text");return (const char*)(v.as.s?v.as.s->data:(const unsigned char*)"");}

static SlugValue sv_cast_i_width(SlugValue a,int bits){
    int64_t sx=0;
    if(a.tag==SV_STRING){if(!sv_text_to_i64_n((const char*)sv_str_data(a),sv_str_len(a),&sx))sv_fail_kind("cast","string is not a decimal integer");a=sv_int(sx);}
    else if(a.tag==SV_BOOL)a=sv_int(a.as.b?1:0);
    if(a.tag==SV_FLOAT){int64_t x=sv_i64_numeric(a);if(bits>0&&bits<64){int64_t lo=-(INT64_C(1)<<(bits-1)),hi=(INT64_C(1)<<(bits-1))-1;if(x<lo||x>hi)sv_fail_kind("cast","signed integer cast out of range");}return sv_int(x);}
    if(a.tag!=SV_INT&&a.tag!=SV_UINT)sv_fail_kind("cast","value cannot be cast to signed integer");
    SvWideInt w=sv_wint(a);uint64_t poshi=bits>=64?(uint64_t)INT64_MAX:((UINT64_C(1)<<(bits-1))-1);uint64_t negmag=bits>=64?UINT64_C(9223372036854775808):(UINT64_C(1)<<(bits-1));
    if((!w.neg&&w.mag>poshi)||(w.neg&&w.mag>negmag))sv_fail_kind("cast","signed integer cast out of range");
    return sv_wint_value(w.neg,w.mag,false);
}
static SlugValue sv_cast_u_width(SlugValue a,int bits){
    uint64_t parsed=0;if(a.tag==SV_STRING){if(!sv_text_to_u64_n((const char*)sv_str_data(a),sv_str_len(a),&parsed))sv_fail_kind("cast","string is not a nonnegative decimal integer");a=sv_uint(parsed);}
    else if(a.tag==SV_BOOL)a=sv_uint(a.as.b?1:0);
    if(a.tag!=SV_INT&&a.tag!=SV_UINT&&a.tag!=SV_FLOAT)sv_fail_kind("cast","value cannot be cast to unsigned integer");
    uint64_t x=sv_u64_numeric(a);if(bits>0&&bits<64){uint64_t hi=(UINT64_C(1)<<bits)-1;if(x>hi)sv_fail_kind("cast","unsigned integer cast out of range");}
    return sv_uint(x);
}
static SlugValue sv_cast_i(SlugValue a){return sv_cast_i_width(a,64);}
static SlugValue sv_cast_u(SlugValue a){return sv_cast_u_width(a,64);}
static SlugValue sv_cast_f(SlugValue a){if(a.tag==SV_STRING){double x=0;if(!sv_text_to_float_n((const char*)sv_str_data(a),sv_str_len(a),&x))sv_fail_kind("cast","string is not a decimal float");return sv_float(x);}if(a.tag==SV_BOOL)return sv_float(a.as.b?1.0:0.0);if(!sv_numeric_tag(a.tag))sv_fail_kind("cast","value cannot be cast to float");return sv_float(sv_num(a));}
static SlugValue sv_contract_i_width(SlugValue a,int bits){if(a.tag!=SV_INT)sv_fail_kind("type","binding contract requires signed integer");if(bits>0&&bits<64){int64_t lo=-(INT64_C(1)<<(bits-1)),hi=(INT64_C(1)<<(bits-1))-1;if(a.as.i<lo||a.as.i>hi)sv_fail_kind("range","signed integer violates binding width contract");}return a;}
static SlugValue sv_contract_u_width(SlugValue a,int bits){if(a.tag!=SV_UINT)sv_fail_kind("type","binding contract requires unsigned integer");if(bits>0&&bits<64){uint64_t hi=(UINT64_C(1)<<bits)-1;if(a.as.u>hi)sv_fail_kind("range","unsigned integer violates binding width contract");}return a;}
static SlugValue sv_contract_f(SlugValue a){if(a.tag!=SV_FLOAT)sv_fail_kind("type","binding contract requires float");return a;}
static SlugValue sv_contract_s(SlugValue a){if(a.tag!=SV_STRING)sv_fail_kind("type","binding contract requires string");return a;}
static SlugValue sv_contract_b(SlugValue a){if(a.tag!=SV_BOOL)sv_fail_kind("type","binding contract requires boolean");return a;}
static SlugValue sv_cast_b(SlugValue a){return sv_bool(sv_truthy(a));}
static SlugValue sv_cast_s(SlugValue a){if(a.tag==SV_STRING)return a;if(a.tag==SV_BYTES){if(!sv_utf8_valid(a.as.bytes->data,a.as.bytes->len))sv_fail_kind("encoding","bytes are not valid UTF-8");return sv_string_n(a.as.bytes->data,a.as.bytes->len);}SvBuf b;sb_init(&b);sv_format_into(&b,a);SlugValue v=sv_string_n(b.p,b.n);free(b.p);return v;}
static SlugValue sv_eval_format_string(void){
    size_t n=sv_eval_count();SlugValue *a=sv_eval_argv(0);size_t total=0;
    /* Codegen already emits explicit @s conversions, but normalizing here keeps the
       runtime primitive defensive and, critically, stores every allocating cast back
       into the evaluation-root array before the next cast can trigger GC. */
    for(size_t i=0;i<n;i++){a[i]=sv_cast_s(a[i]);total=sv_size_add_or_fail(total,sv_str_len(a[i]),"formatted string size overflow");}
    unsigned char *buf=total?(unsigned char*)sv_xmalloc(total):NULL;size_t at=0;
    for(size_t i=0;i<n;i++){size_t z=sv_str_len(a[i]);if(z)memcpy(buf+at,sv_str_data(a[i]),z);at+=z;}
    SlugValue out=sv_string_n(buf,total);free(buf);sv_eval_finish();return out;
}

typedef struct { char base; int bits; bool valid; } SvTypeDesc;
static SvTypeDesc sv_type_desc_text(const char *s){
    SvTypeDesc d={0,0,false};if(!s||!*s)return d;d.base=s[0];if(!strchr("iufsb",d.base))return d;const char *w=s+1;
    if(d.base=='s'||d.base=='b'){if(*w)return d;d.bits=0;d.valid=true;return d;}
    if(!*w){d.bits=(d.base=='f'?64:64);d.valid=true;return d;}
    char *e=NULL;long n=strtol(w,&e,10);if(!e||*e)return d;
    if((d.base=='i'||d.base=='u')&&(n==8||n==16||n==32||n==64)){d.bits=(int)n;d.valid=true;return d;}
    if(d.base=='f'&&n==64){d.bits=64;d.valid=true;return d;}
    return d;
}
static bool sv_can_cast_desc(SvTypeDesc d,SlugValue a){
    if(!d.valid||a.tag==SV_DEFAULT)return false;
    if(d.base=='s'){
        if(a.tag!=SV_BYTES)return true;
        if(!a.as.bytes)return true;
        return sv_utf8_valid(a.as.bytes->data,a.as.bytes->len);
    }
    if(d.base=='b')return true;
    if(d.base=='f'){
        if(a.tag==SV_INT||a.tag==SV_UINT||a.tag==SV_FLOAT)return true;
        double x=0;return a.tag==SV_STRING&&sv_text_to_float_n((const char*)sv_str_data(a),sv_str_len(a),&x);
    }
    if(d.base=='i'){
        int64_t x=0;if(a.tag==SV_STRING){if(!sv_text_to_i64_n((const char*)sv_str_data(a),sv_str_len(a),&x))return false;}
        else if(a.tag==SV_INT)x=a.as.i;
        else if(a.tag==SV_UINT){if(a.as.u>(uint64_t)INT64_MAX)return false;x=(int64_t)a.as.u;}
        else if(a.tag==SV_FLOAT){if(!isfinite(a.as.f)||a.as.f < -9223372036854775808.0 || a.as.f >= 9223372036854775808.0)return false;x=(int64_t)a.as.f;}
        else return false;
        int bits=d.bits?d.bits:64;if(bits<64){int64_t lo=-(INT64_C(1)<<(bits-1)),hi=(INT64_C(1)<<(bits-1))-1;if(x<lo||x>hi)return false;}return true;
    }
    if(d.base=='u'){
        uint64_t x=0;if(a.tag==SV_STRING){if(!sv_text_to_u64_n((const char*)sv_str_data(a),sv_str_len(a),&x))return false;}
        else if(a.tag==SV_UINT)x=a.as.u;
        else if(a.tag==SV_INT){if(a.as.i<0)return false;x=(uint64_t)a.as.i;}
        else if(a.tag==SV_FLOAT){if(!isfinite(a.as.f)||a.as.f<0.0||a.as.f>=18446744073709551616.0)return false;x=(uint64_t)a.as.f;}
        else return false;
        int bits=d.bits?d.bits:64;if(bits<64){uint64_t hi=(UINT64_C(1)<<bits)-1;if(x>hi)return false;}return true;
    }
    return false;
}
static SlugValue sv_cast_dynamic(SlugValue typev,SlugValue value){
    if(typev.tag!=SV_STRING)sv_fail_kind("type","dynamic cast type must be a type string");if(sv_string_has_nul(typev))sv_fail_kind("cast","invalid dynamic cast type");SvTypeDesc d=sv_type_desc_text((const char*)sv_str_data(typev));if(!d.valid)sv_fail_kind("cast","invalid dynamic cast type");
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
        case SV_OBJECT:{const char *n=(v.as.obj&&v.as.obj->class_name)?v.as.obj->class_name:"object";size_t k=strlen(n),z=sv_size_add_or_fail(k,8,"type name overflow");char *p=(char*)sv_xmalloc(z);memcpy(p,"object:",7);memcpy(p+7,n,k+1);return sv_string_owned(p);}
    }
    return sv_string("unknown");
}
static SlugValue sv_can_convert_value(SlugValue typev,SlugValue value){if(typev.tag!=SV_STRING||sv_string_has_nul(typev))return sv_bool(false);return sv_bool(sv_can_cast_desc(sv_type_desc_text((const char*)sv_str_data(typev)),value));}
static SlugValue sv_inc(SlugValue a){return sv_add(a,sv_int(1));}
static SlugValue sv_dec(SlugValue a){return sv_sub(a,sv_int(1));}
static SlugValue sv_eval_object_mutate(const char *name,bool increment){if(sv_eval_count()!=1)sv_fail("member mutation evaluation arity");SlugValue base=sv_eval_argv(0)[0];SlugValue old=sv_object_get(base,name);SlugValue value=increment?sv_inc(old):sv_dec(old);value=sv_object_set(base,name,value,false,false,false);sv_eval_finish();return value;}

static SlugValue sv_size_value(size_t n){return n<=(size_t)INT64_MAX?sv_int((int64_t)n):sv_uint((uint64_t)n);}
static size_t sv_len_size(SlugValue v){
    if(v.tag==SV_STRING)return sv_str_cp_len(v);if(v.tag==SV_BYTES)return v.as.bytes?v.as.bytes->len:0;if(v.tag==SV_LIST)return v.as.list?v.as.list->len:0;if(v.tag==SV_MAP)return v.as.map?v.as.map->len:0;sv_fail_kind("type","ln requires string/bytes/list/map");return 0;
}
static size_t sv_index_position(SlugValue iv,size_t n){
    if(iv.tag==SV_UINT){if(iv.as.u>(uint64_t)SIZE_MAX||(size_t)iv.as.u>=n)sv_fail_kind("index","index out of range");return(size_t)iv.as.u;}
    if(iv.tag!=SV_INT)sv_fail_kind("type","index must be an integer");
    if(iv.as.i>=0){uint64_t u=(uint64_t)iv.as.i;if(u>(uint64_t)SIZE_MAX||(size_t)u>=n)sv_fail_kind("index","index out of range");return(size_t)u;}
    uint64_t mag=(uint64_t)(-(iv.as.i+1))+1;if(mag>(uint64_t)n)sv_fail_kind("index","index out of range");return n-(size_t)mag;
}
static SlugValue sv_index(SlugValue base,SlugValue index){
    if(base.tag==SV_LIST){size_t i=sv_index_position(index,base.as.list->len);return base.as.list->items[i];}
    if(base.tag==SV_BYTES){size_t i=sv_index_position(index,base.as.bytes->len);return sv_uint(base.as.bytes->data[i]);}
    if(base.tag==SV_STRING){size_t bytes=sv_str_len(base),cp=sv_str_cp_len(base),k=sv_index_position(index,cp);if(sv_str_ascii(base))return sv_string_n(sv_str_data(base)+k,1);size_t a=sv_utf8_offset_n((const char*)sv_str_data(base),bytes,k),b=sv_utf8_offset_n((const char*)sv_str_data(base),bytes,k+1);return sv_string_n(sv_str_data(base)+a,b-a);}
    if(base.tag==SV_MAP){size_t i;if(!sv_map_find(base.as.map,index,&i))sv_fail_kind("key","missing map key");return base.as.map->vals[i];}
    sv_fail_kind("type","value is not indexable");return sv_null();
}
typedef struct { bool neg; uint64_t mag; } SvStep;
static SvStep sv_slice_step(SlugValue v){if(v.tag==SV_NULL)return(SvStep){false,1};SvWideInt w=sv_wint(v);if(w.mag==0)sv_fail_kind("range","zero slice step");return(SvStep){w.neg,w.mag};}
static size_t sv_bound_positive(SlugValue v,size_t n,size_t def){if(v.tag==SV_NULL)return def;if(v.tag==SV_UINT)return v.as.u>(uint64_t)n?n:(size_t)v.as.u;if(v.tag!=SV_INT)sv_fail_kind("type","slice bound must be integer or nn");if(v.as.i>=0){uint64_t u=(uint64_t)v.as.i;return u>(uint64_t)n?n:(size_t)u;}uint64_t mag=(uint64_t)(-(v.as.i+1))+1;return mag>(uint64_t)n?0:n-(size_t)mag;}
static bool sv_bound_negative(SlugValue v,size_t n,bool is_start,size_t *out){
    if(v.tag==SV_NULL){if(is_start){if(!n)return false;*out=n-1;return true;}return false;}
    if(!n)return false;
    if(v.tag==SV_UINT){*out=v.as.u>=(uint64_t)n?n-1:(size_t)v.as.u;return true;}
    if(v.tag!=SV_INT)sv_fail_kind("type","slice bound must be integer or nn");
    if(v.as.i>=0){uint64_t u=(uint64_t)v.as.i;*out=u>=(uint64_t)n?n-1:(size_t)u;return true;}
    uint64_t mag=(uint64_t)(-(v.as.i+1))+1;if(mag>(uint64_t)n)return false;*out=n-(size_t)mag;return true;
}
typedef struct { bool reverse; uint64_t stride; size_t start,count; } SvSliceNorm;
static SvSliceNorm sv_slice_norm(size_t n,SlugValue startv,SlugValue stopv,SlugValue stepv){
    SvStep st=sv_slice_step(stepv);SvSliceNorm r={st.neg,st.mag,0,0};if(!st.neg){size_t a=sv_bound_positive(startv,n,0),b=sv_bound_positive(stopv,n,n);r.start=a;if(a<b){uint64_t span=(uint64_t)(b-a);r.count=(size_t)(1+(span-1)/st.mag);}return r;}
    size_t a=0,b=0;bool ah=sv_bound_negative(startv,n,true,&a),bh=sv_bound_negative(stopv,n,false,&b);if(!ah)return r;r.start=a;if(!bh){r.count=(size_t)(1+(uint64_t)a/st.mag);return r;}if(a>b){uint64_t span=(uint64_t)(a-b);r.count=(size_t)(1+(span-1)/st.mag);}return r;
}
static size_t sv_slice_at(SvSliceNorm r,size_t k){uint64_t delta=(uint64_t)k*r.stride;return r.reverse?r.start-(size_t)delta:r.start+(size_t)delta;}
static SlugValue sv_slice(SlugValue base,SlugValue startv,SlugValue stopv,SlugValue stepv){
    if(base.tag!=SV_LIST&&base.tag!=SV_STRING&&base.tag!=SV_BYTES)sv_fail_kind("type","slice requires list/string/bytes");size_t n=base.tag==SV_STRING?sv_str_cp_len(base):(base.tag==SV_LIST?base.as.list->len:base.as.bytes->len);SvSliceNorm r=sv_slice_norm(n,startv,stopv,stepv);
    if(base.tag==SV_LIST){SlugList *l=sv_list_new_raw(base.as.list->frozen,r.count);for(size_t k=0;k<r.count;k++)l->items[k]=base.as.list->items[sv_slice_at(r,k)];return sv_list_value(l);}
    if(base.tag==SV_BYTES){unsigned char *buf=r.count?(unsigned char*)sv_xmalloc(r.count):NULL;for(size_t k=0;k<r.count;k++)buf[k]=base.as.bytes->data[sv_slice_at(r,k)];SlugValue v=sv_bytes(buf,r.count);free(buf);return v;}
    SvBuf b;sb_init(&b);size_t bytes=sv_str_len(base);if(sv_str_ascii(base)){for(size_t k=0;k<r.count;k++){size_t cp=sv_slice_at(r,k);sb_ch(&b,sv_str_data(base)[cp]);}}else{for(size_t k=0;k<r.count;k++){size_t cp=sv_slice_at(r,k),x=sv_utf8_offset_n((const char*)sv_str_data(base),bytes,cp),y=sv_utf8_offset_n((const char*)sv_str_data(base),bytes,cp+1);sb_add_n(&b,sv_str_data(base)+x,y-x);}}SlugValue v=sv_string_n(b.p,b.n);free(b.p);return v;
}
static SlugValue sv_set_index(SlugValue base,SlugValue index,SlugValue value,bool create){
    if(base.tag==SV_LIST){if(base.as.list->frozen)sv_fail_kind("immutable","cannot mutate frozen list");size_t i=sv_index_position(index,base.as.list->len);base.as.list->items[i]=value;return value;}
    if(base.tag==SV_MAP){if(base.as.map->frozen)sv_fail_kind("immutable","cannot mutate frozen map");if(!sv_stable_map_key(index))sv_fail_kind("key","unstable map key type");size_t i;if(!sv_map_find(base.as.map,index,&i)){if(!create)sv_fail_kind("key","missing map key");sv_map_put_raw(base.as.map,index,value);}else base.as.map->vals[i]=value;return value;}
    if(base.tag==SV_STRING)sv_fail_kind("immutable","strings are immutable");sv_fail_kind("type","indexed assignment requires list/map");return sv_null();
}
static SlugValue sv_eval_set_index(bool define){if(sv_eval_count()!=3)sv_fail("indexed assignment evaluation arity");SlugValue *a=sv_eval_argv(0);SlugValue v=sv_set_index(a[0],a[1],a[2],define);sv_eval_finish();return v;}
static SlugValue sv_eval_slice(void){if(sv_eval_count()!=4)sv_fail("slice evaluation arity");SlugValue *a=sv_eval_argv(0);SlugValue v=sv_slice(a[0],a[1],a[2],a[3]);sv_eval_finish();return v;}
static bool sv_bytes_contains(const unsigned char *hay,size_t hn,const unsigned char *needle,size_t nn){if(!nn)return true;if(nn>hn)return false;for(size_t i=0;i<=hn-nn;i++)if(memcmp(hay+i,needle,nn)==0)return true;return false;}
static SlugValue sv_in(SlugValue needle,SlugValue hay){
    if(hay.tag==SV_BYTES){uint64_t x=sv_u64_numeric(needle);if(x>255)sv_fail_kind("range","byte membership value out of range");for(size_t i=0;i<hay.as.bytes->len;i++)if(hay.as.bytes->data[i]==(unsigned char)x)return sv_bool(true);return sv_bool(false);}
    if(hay.tag==SV_LIST){for(size_t i=0;i<hay.as.list->len;i++)if(sv_equal(needle,hay.as.list->items[i]))return sv_bool(true);return sv_bool(false);}
    if(hay.tag==SV_STRING){if(needle.tag!=SV_STRING)sv_fail_kind("type","string membership requires string needle");return sv_bool(sv_bytes_contains(sv_str_data(hay),sv_str_len(hay),sv_str_data(needle),sv_str_len(needle)));}
    if(hay.tag==SV_MAP){size_t i;return sv_bool(sv_map_find(hay.as.map,needle,&i));}sv_fail_kind("type","in requires list/string/map haystack");return sv_bool(false);
}
static SlugValue sv_iv(SlugValue needle,SlugValue hay){if(hay.tag!=SV_MAP)sv_fail_kind("type","iv requires map");for(size_t i=0;i<hay.as.map->len;i++)if(sv_equal(needle,hay.as.map->vals[i]))return sv_bool(true);return sv_bool(false);}
static SlugValue sv_ln(SlugValue v){return sv_size_value(sv_len_size(v));}
static SlugValue sv_sl(SlugValue v){
    if(v.tag!=SV_LIST)sv_fail_kind("type","sl requires list");if(v.as.list->frozen)sv_fail_kind("immutable","cannot sort frozen list");SlugValue tmpv=sv_list_from(v.as.list->items,v.as.list->len,false);size_t mark=sv_temp_root_push(tmpv);SlugList *tmp=tmpv.as.list;
    for(size_t i=1;i<tmp->len;i++){SlugValue x=tmp->items[i];size_t j=i;while(j>0&&sv_compare(tmp->items[j-1],x)>0){tmp->items[j]=tmp->items[j-1];j--;}tmp->items[j]=x;}if(tmp->len)memcpy(v.as.list->items,tmp->items,sv_size_mul_or_fail(sizeof(SlugValue),tmp->len,"sort copy overflow"));sv_temp_root_pop(mark);return v;
}
static SlugValue sv_iteration_snapshot(SlugValue v){if(v.tag==SV_LIST)return sv_list_from(v.as.list->items,v.as.list->len,true);if(v.tag==SV_MAP)return sv_list_from(v.as.map->keys,v.as.map->len,true);if(v.tag==SV_STRING||v.tag==SV_BYTES)return v;sv_fail_kind("type","value is not iterable");return sv_null();}
static SlugValue sv_iter_at(SlugValue v,size_t i){if(v.tag==SV_LIST){if(i>=v.as.list->len)sv_fail_kind("index","iteration index out of range");return v.as.list->items[i];}if(v.tag==SV_BYTES){if(i>=v.as.bytes->len)sv_fail_kind("index","iteration index out of range");return sv_uint(v.as.bytes->data[i]);}if(v.tag==SV_STRING){size_t n=sv_str_cp_len(v);if(i>=n)sv_fail_kind("index","iteration index out of range");if(sv_str_ascii(v))return sv_string_n(sv_str_data(v)+i,1);size_t x=sv_utf8_offset_n((const char*)sv_str_data(v),sv_str_len(v),i),y=sv_utf8_offset_n((const char*)sv_str_data(v),sv_str_len(v),i+1);return sv_string_n(sv_str_data(v)+x,y-x);}sv_fail_kind("type","iteration snapshot required");return sv_null();}
static void sv_require_range_bound(SlugValue v){if(v.tag!=SV_INT&&v.tag!=SV_UINT)sv_fail_kind("type","range bound must be integer");}
static uint64_t sv_repeat_count(SlugValue v){if(v.tag==SV_UINT)return v.as.u;if(v.tag==SV_INT){if(v.as.i<0)sv_fail_kind("range","negative repeat count");return(uint64_t)v.as.i;}sv_fail_kind("type","repeat count must be integer");return 0;}
static SlugValue sv_range_next(SlugValue v,bool allow_unsigned){if(v.tag==SV_UINT){if(v.as.u==UINT64_MAX)sv_fail_kind("overflow","range iterator overflow");return sv_uint(v.as.u+1);}if(v.tag!=SV_INT)sv_fail_kind("type","range bound must be integer");if(v.as.i==INT64_MAX){if(allow_unsigned)return sv_uint((uint64_t)INT64_MAX+1u);sv_fail_kind("overflow","range iterator overflow");}return sv_int(v.as.i+1);}

static SlugValue sv_co(SlugValue a){SvBuf b;sb_init(&b);sv_format_into(&b,a);if(b.n)fwrite(b.p,1,b.n,stdout);fputc('\n',stdout);fflush(stdout);free(b.p);return sv_null();}
static SlugValue sv_ci(SlugValue prompt){if(prompt.tag!=SV_STRING)sv_fail_kind("type","ci prompt must be string");if(sv_str_len(prompt))fwrite(sv_str_data(prompt),1,sv_str_len(prompt),stdout);fflush(stdout);SvBuf b;sb_init(&b);int ch;bool any=false;while((ch=fgetc(stdin))!=EOF){any=true;if(ch=='\n')break;sb_ch(&b,(unsigned char)ch);}if(!any&&ch==EOF){free(b.p);return sv_null();}if(b.n&&b.p[b.n-1]=='\r'){b.n--;b.p[b.n]=0;}SlugValue out=sv_string_n(b.p,b.n);free(b.p);return out;}
static SlugValue sv_by(SlugValue v){if(v.tag==SV_BYTES)return v;if(v.tag==SV_STRING)return sv_bytes(sv_str_data(v),sv_str_len(v));if(v.tag==SV_LIST){size_t n=v.as.list->len;unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;for(size_t i=0;i<n;i++){uint64_t x=sv_u64_numeric(v.as.list->items[i]);if(x>255)sv_fail_kind("range","byte value out of range");p[i]=(unsigned char)x;}SlugValue out=sv_bytes(p,n);free(p);return out;}sv_fail_kind("type","by requires string/list/bytes");return sv_null();}

/* Native capability foundation.  These are deliberately the OS boundary; higher-level
   copy/walk/glob/PRNG/protocol helpers belong in SLUG code. */
static const char *sv_require_string(SlugValue v,const char *what){return sv_string_cstr_boundary(v,what);}
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
static wchar_t *sv_widen(const char *s){int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,NULL,0);if(!n)sv_fail("invalid UTF-8 path");wchar_t *w=(wchar_t*)sv_xmalloc(sv_size_mul_or_fail(sizeof(wchar_t),(size_t)n,"wide-text allocation overflow"));if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,w,n)){free(w);sv_fail("path conversion failed");}return w;}
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
    for(;;){if(n==cap){size_t next;if(!sv_size_mul(cap,2,&next)){fclose(f);free(p);sv_fail_kind("resource","file too large for host address space");}cap=next;p=(unsigned char*)sv_xrealloc(p,cap);}size_t got=fread(p+n,1,cap-n,f);n+=got;if(got==0){if(ferror(f)){fclose(f);free(p);sv_fail_kind("io","file read failed");}break;}}
    fclose(f);SlugValue v=sv_bytes(p,n);free(p);return v;
}
static SlugValue sv_read_file_text(const char *path){SlugValue b=sv_read_file_bytes(path);if(!sv_utf8_valid(b.as.bytes->data,b.as.bytes->len))sv_fail_kind("encoding","text file is not valid UTF-8");return sv_string_n(b.as.bytes->data,b.as.bytes->len);}
static size_t sv_write_payload(FILE *f,SlugValue data){const unsigned char *p;size_t n;if(data.tag==SV_BYTES){p=data.as.bytes->data;n=data.as.bytes->len;}else if(data.tag==SV_STRING){p=sv_str_data(data);n=sv_str_len(data);}else sv_fail_kind("type","file write requires string/bytes");size_t off=0;while(off<n){size_t wrote=fwrite(p+off,1,n-off,f);if(!wrote){if(ferror(f))sv_fail_kind("io","file write failed");sv_fail_kind("io","file write made no progress");}off+=wrote;}if(fflush(f)!=0)sv_fail_kind("io","file flush failed");return n;}
static SlugValue sv_write_file(const char *path,SlugValue data,bool append){
#ifdef _WIN32
    FILE *f=sv_fopen_utf8(path,append?L"ab":L"wb");
#else
    FILE *f=sv_fopen_utf8(path,append?"ab":"wb");
#endif
    if(!f)sv_fail("cannot open file for writing");size_t n=sv_write_payload(f,data);if(fclose(f)!=0)sv_fail("file close failed");return sv_size_value(n);
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
    wchar_t *w=sv_widen(path);size_t n=wcslen(w);size_t pn=sv_size_add_or_fail(n,3,"directory pattern overflow");wchar_t *pat=(wchar_t*)sv_xmalloc(sv_size_mul_or_fail(sizeof(wchar_t),pn,"directory pattern overflow"));wcscpy(pat,w);if(n&&w[n-1]!=L'\\'&&w[n-1]!=L'/')pat[n++]=L'\\';pat[n++]=L'*';pat[n]=0;WIN32_FIND_DATAW d;HANDLE h=FindFirstFileW(pat,&d);free(pat);free(w);if(h==INVALID_HANDLE_VALUE){DWORD e=GetLastError();if(e==ERROR_FILE_NOT_FOUND)return sv_list_value(l);sv_fail("directory listing failed");}do{if(wcscmp(d.cFileName,L".")&&wcscmp(d.cFileName,L"..")){char *x=sv_narrow(d.cFileName);sv_list_append(l,sv_string(x));free(x);}}while(FindNextFileW(h,&d));FindClose(h);
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
static SlugValue sv_cli_stderr_value(SlugValue v){const char *s=sv_require_string(v,"internal cli stderr requires string");size_t n=sv_str_len(v);if(n)fwrite(s,1,n,stderr);fputc('\n',stderr);fflush(stderr);return sv_null();}
static SlugValue sv_cli_stdout_value(SlugValue v){const char *s=sv_require_string(v,"internal cli stdout requires string");size_t n=sv_str_len(v);if(n)fwrite(s,1,n,stdout);fflush(stdout);return sv_null();}
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
    DWORD n=GetCurrentDirectoryW(0,NULL);if(!n)sv_fail("cwd failed");wchar_t *w=(wchar_t*)sv_xmalloc(sv_size_mul_or_fail(sizeof(wchar_t),(size_t)n,"wide-text allocation overflow"));if(!GetCurrentDirectoryW(n,w)){free(w);sv_fail("cwd failed");}char *x=sv_narrow(w);free(w);return sv_string_owned(x);
#else
    size_t cap=256;for(;;){char *p=(char*)sv_xmalloc(cap);if(getcwd(p,cap))return sv_string_owned(p);free(p);if(errno!=ERANGE)sv_fail_kind("io","cwd failed");cap=sv_size_mul_or_fail(cap,2,"cwd buffer overflow");}
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
static bool sv_string_is_ascii_literal(SlugValue v,const char *lit){
    if(v.tag!=SV_STRING||!lit)return false;
    size_t n=strlen(lit);
    return sv_str_len(v)==n&&(n==0||memcmp(sv_str_data(v),lit,n)==0);
}
static SlugValue sv_capability_present(SlugValue name){
    /*
     * Canonical probe ids are "@std/module.export".  Module import succeeds on all
     * supported compiler targets; cp reports whether an operation has an actual host
     * implementation here.  Pure in-memory surface operations are available even on
     * targets without a native window backend.  Unknown/future names are false.
     */
    if(name.tag!=SV_STRING)return sv_bool(false);
    const char *always[]={
        "@std/sys.av","@std/sys.ev","@std/sys.cw","@std/sys.pf","@std/sys.cp","@std/sys.pc",
        "@std/time.tm","@std/time.mt","@std/time.wt","@std/rand.en",
        "@std/fs.fr","@std/fs.ft","@std/fs.fw","@std/fs.fa","@std/fs.fe","@std/fs.fd","@std/fs.fm",
        "@std/fs.md","@std/fs.rm","@std/fs.mv","@std/fs.fo","@std/fs.hr","@std/fs.hw","@std/fs.hs",
        "@std/fs.hp","@std/fs.hf","@std/fs.hc",
        "@std/net.so","@std/net.cn","@std/net.bn","@std/net.ls","@std/net.ac","@std/net.sd","@std/net.rc",
        "@std/net.sc","@std/net.gp",
        "@std/gfx.sf","@std/gfx.px","@std/gfx.rf","@std/gfx.dl","@std/gfx.sb",
        "@std/dev.do","@std/dev.dv","@std/dev.dr","@std/dev.dw","@std/dev.dx",
        "@std/list.ap","@std/list.ip","@std/list.rm","@std/list.pp"
    };
    for(size_t i=0;i<sizeof(always)/sizeof(always[0]);i++)if(sv_string_is_ascii_literal(name,always[i]))return sv_bool(true);
#ifdef _WIN32
    const char *win[]={"@std/gfx.wn","@std/gfx.wf","@std/gfx.pe","@std/gfx.wx","@std/audio.au","@std/audio.aq","@std/audio.ax"};
    for(size_t i=0;i<sizeof(win)/sizeof(win[0]);i++)if(sv_string_is_ascii_literal(name,win[i]))return sv_bool(true);
#endif
    return sv_bool(false);
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
static SlugValue sv_wait_seconds(SlugValue v){if(!sv_numeric_tag(v.tag))sv_fail_kind("type","sleep duration must be numeric");double x=sv_num(v);if(x<0)sv_fail_kind("range","negative sleep duration");
#ifdef _WIN32
    const double maxs=4294967294.0/1000.0;while(x>maxs){Sleep((DWORD)4294967294u);x-=maxs;}double ms=x*1000.0;DWORD tail=(DWORD)(ms+0.5);if(tail)Sleep(tail);
#else
    const double chunk=86400.0;while(x>chunk){struct timespec req={(time_t)86400,0};while(nanosleep(&req,&req)!=0)if(errno!=EINTR)sv_fail_kind("io","sleep failed");x-=chunk;}time_t sec=(time_t)floor(x);long ns=(long)((x-(double)sec)*1e9);if(ns<0)ns=0;if(ns>999999999L)ns=999999999L;struct timespec req={sec,ns};while(nanosleep(&req,&req)!=0)if(errno!=EINTR)sv_fail_kind("io","sleep failed");
#endif
    return sv_null();
}
static size_t sv_request_size(SlugValue v,const char *what){if(v.tag==SV_UINT){if(v.as.u>(uint64_t)SIZE_MAX)sv_fail_kind("range",what);return(size_t)v.as.u;}if(v.tag==SV_INT){if(v.as.i<0)sv_fail_kind("range",what);return(size_t)v.as.i;}sv_fail_kind("type","size request must be integer");return 0;}
static uint64_t sv_nonnegative_integer(SlugValue v,const char *what){if(v.tag==SV_UINT)return v.as.u;if(v.tag==SV_INT){if(v.as.i<0)sv_fail_kind("range",what);return(uint64_t)v.as.i;}sv_fail_kind("type","integer value required");return 0;}
static int64_t sv_signed_integer(SlugValue v,const char *what){if(v.tag==SV_INT)return v.as.i;if(v.tag==SV_UINT){if(v.as.u>(uint64_t)INT64_MAX)sv_fail_kind("range",what);return(int64_t)v.as.u;}sv_fail_kind("type","integer value required");return 0;}
static SlugValue sv_entropy_value(SlugValue nv){size_t n=sv_request_size(nv,"entropy length out of range");unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;
#ifdef _WIN32
    size_t i=0;while(i<n){unsigned int x;if(rand_s(&x)!=0){free(p);sv_fail_kind("io","system entropy failed");}for(unsigned k=0;k<sizeof(x)&&i<n;k++,i++)p[i]=(unsigned char)(x>>(k*8));}
#else
    FILE *f=fopen("/dev/urandom","rb");if(!f){free(p);sv_fail_kind("capability","system entropy unavailable");}size_t off=0;while(off<n){size_t chunk=n-off;const size_t soft_chunk=1024u*1024u;if(chunk>soft_chunk)chunk=soft_chunk;size_t got=fread(p+off,1,chunk,f);if(!got){if(ferror(f)){fclose(f);free(p);sv_fail_kind("io","system entropy failed");}fclose(f);free(p);sv_fail_kind("io","system entropy ended early");}off+=got;}fclose(f);
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
static SlugValue sv_file_handle_read(SlugValue fv,SlugValue nv){SlugFile *f=sv_require_file(fv);size_t want=sv_request_size(nv,"file read length out of range");if(!want)return sv_bytes(NULL,0);SvBuf b;sb_init(&b);const size_t chunk=1024u*1024u;while(b.n<want){size_t ask=want-b.n;if(ask>chunk)ask=chunk;sb_need(&b,ask);size_t got=fread(b.p+b.n,1,ask,f->f);b.n+=got;b.p[b.n]=0;if(got<ask){if(ferror(f->f)){free(b.p);sv_fail_kind("io","file handle read failed");}break;}}SlugValue out=sv_bytes(b.p,b.n);free(b.p);return out;}
static SlugValue sv_file_handle_write(SlugValue fv,SlugValue data){SlugFile *f=sv_require_file(fv);size_t n=sv_write_payload(f->f,data);return sv_size_value(n);}
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

static SlugValue sv_process_run(SlugValue av){if(av.tag!=SV_LIST||!av.as.list->len)sv_fail("pc requires non-empty argv list");size_t n=av.as.list->len;for(size_t i=0;i<n;i++){if(av.as.list->items[i].tag!=SV_STRING)sv_fail_kind("type","pc argv entries must be strings");(void)sv_string_cstr_boundary(av.as.list->items[i],"pc argv entries must be strings");}
#ifdef _WIN32
    SvBuf cmd;sb_init(&cmd);for(size_t ai=0;ai<n;ai++){const char *a=(const char*)sv_str_data(av.as.list->items[ai]);if(ai)sb_ch(&cmd,' ');sb_ch(&cmd,'\"');const char *p=a;for(;;){size_t bs=0;while(*p=='\\'){bs++;p++;}if(*p=='\"'){for(size_t k=0;k<bs;k++){sb_ch(&cmd,'\\');sb_ch(&cmd,'\\');}sb_ch(&cmd,'\\');sb_ch(&cmd,'\"');p++;continue;}if(*p=='\0'){for(size_t k=0;k<bs;k++){sb_ch(&cmd,'\\');sb_ch(&cmd,'\\');}break;}for(size_t k=0;k<bs;k++)sb_ch(&cmd,'\\');sb_ch(&cmd,*p++);}sb_ch(&cmd,'\"');}wchar_t *w=sv_widen(cmd.p);free(cmd.p);STARTUPINFOW si;PROCESS_INFORMATION pi;memset(&si,0,sizeof(si));memset(&pi,0,sizeof(pi));si.cb=sizeof(si);BOOL ok=CreateProcessW(NULL,w,NULL,NULL,FALSE,0,NULL,NULL,&si,&pi);free(w);if(!ok)sv_fail("process spawn failed");WaitForSingleObject(pi.hProcess,INFINITE);DWORD code=0;if(!GetExitCodeProcess(pi.hProcess,&code)){CloseHandle(pi.hThread);CloseHandle(pi.hProcess);sv_fail("process wait failed");}CloseHandle(pi.hThread);CloseHandle(pi.hProcess);return sv_int((int64_t)code);
#else
    size_t argn=sv_size_add_or_fail(n,1,"process argv overflow");char **args=(char**)sv_xmalloc(sv_size_mul_or_fail(sizeof(char*),argn,"process argv overflow"));for(size_t i=0;i<n;i++)args[i]=(char*)sv_str_data(av.as.list->items[i]);args[n]=NULL;pid_t pid=fork();if(pid<0){free(args);sv_fail("process spawn failed");}if(pid==0){execvp(args[0],args);_exit(127);}free(args);int status=0;while(waitpid(pid,&status,0)<0){if(errno==EINTR)continue;sv_fail("process wait failed");}if(WIFEXITED(status))return sv_int(WEXITSTATUS(status));if(WIFSIGNALED(status))return sv_int(128+WTERMSIG(status));sv_fail("process ended without status");
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
static uint16_t sv_port(SlugValue v){uint64_t p=sv_nonnegative_integer(v,"socket port out of range");if(p>65535)sv_fail_kind("range","socket port out of range");return (uint16_t)p;}
static SlugValue sv_socket_connect(SlugValue sv,SlugValue hostv,SlugValue portv){SlugSocket *s=sv_require_socket(sv);struct sockaddr_storage a;SvSockLen n;sv_socket_addr(sv_require_string(hostv,"socket host must be string"),sv_port(portv),false,&a,&n);if(connect(s->h,(struct sockaddr*)&a,n)!=0)sv_fail("socket connect failed");return sv_null();}
static SlugValue sv_socket_bind(SlugValue sv,SlugValue hostv,SlugValue portv){SlugSocket *s=sv_require_socket(sv);int one=1;setsockopt(s->h,SOL_SOCKET,SO_REUSEADDR,(const char*)&one,sizeof(one));struct sockaddr_storage a;SvSockLen n;sv_socket_addr(sv_require_string(hostv,"socket host must be string"),sv_port(portv),true,&a,&n);if(bind(s->h,(struct sockaddr*)&a,n)!=0)sv_fail("socket bind failed");return sv_null();}
static SlugValue sv_socket_listen(SlugValue sv,SlugValue backlogv){SlugSocket *s=sv_require_socket(sv);uint64_t b=sv_nonnegative_integer(backlogv,"socket backlog out of range");if(b>(uint64_t)INT_MAX)sv_fail_kind("range","socket backlog outside host representability");if(listen(s->h,(int)b)!=0)sv_fail_kind("io","socket listen failed");return sv_null();}
static SlugValue sv_socket_accept(SlugValue sv){SlugSocket *s=sv_require_socket(sv);SvSocketHandle h=accept(s->h,NULL,NULL);if(h==SV_BAD_SOCKET)sv_fail("socket accept failed");return sv_socket_value(h);}
static SlugValue sv_socket_send(SlugValue sv,SlugValue data){SlugSocket *s=sv_require_socket(sv);const unsigned char *p;size_t n;if(data.tag==SV_BYTES){p=data.as.bytes->data;n=data.as.bytes->len;}else if(data.tag==SV_STRING){p=sv_str_data(data);n=sv_str_len(data);}else sv_fail_kind("type","socket send requires string/bytes");size_t sent=0;while(sent<n){size_t left=n-sent;int chunk=left>(size_t)INT_MAX?INT_MAX:(int)left;
#ifdef _WIN32
int r=send(s->h,(const char*)p+sent,chunk,0);
#else
ssize_t r=send(s->h,p+sent,(size_t)chunk,0);
#endif
if(r<=0)sv_fail_kind("io","socket send failed");sent+=(size_t)r;}return sv_size_value(sent);}
static SlugValue sv_socket_recv(SlugValue sv,SlugValue maxv){SlugSocket *s=sv_require_socket(sv);size_t requested=sv_request_size(maxv,"socket receive length out of range");size_t n=requested;const size_t soft_chunk=1024u*1024u;if(n>soft_chunk)n=soft_chunk;
#ifdef _WIN32
if(n>(size_t)INT_MAX)n=INT_MAX;
#endif
unsigned char *p=n?(unsigned char*)sv_xmalloc(n):NULL;
#ifdef _WIN32
int r=n?recv(s->h,(char*)p,(int)n,0):0;if(r==SOCKET_ERROR){free(p);sv_fail_kind("io","socket receive failed");}
#else
ssize_t r=n?recv(s->h,p,n,0):0;if(r<0){free(p);sv_fail_kind("io","socket receive failed");}
#endif
SlugValue out=sv_bytes(p,(size_t)r);free(p);return out;}
static SlugValue sv_socket_close(SlugValue sv){if(sv.tag!=SV_SOCKET||!sv.as.sock)sv_fail("socket required");sv_socket_close_raw(sv.as.sock);return sv_null();}
static SlugValue sv_socket_port(SlugValue sv){SlugSocket *s=sv_require_socket(sv);struct sockaddr_in a;SvSockLen n=(SvSockLen)sizeof(a);if(getsockname(s->h,(struct sockaddr*)&a,&n)!=0)sv_fail("socket port query failed");return sv_int((int64_t)ntohs(a.sin_port));}

/* v0.1.7 low-level surface / host-I/O bones. */
static SlugSurface *sv_require_surface(SlugValue v){if(v.tag!=SV_SURFACE||!v.as.surface)sv_fail("surface required");return v.as.surface;}
static SlugValue sv_surface_new_value(SlugValue wv,SlugValue hv){size_t w=sv_request_size(wv,"surface width out of range"),h=sv_request_size(hv,"surface height out of range");if(!w||!h)sv_fail_kind("range","surface dimensions must be positive");size_t pixels=sv_size_mul_or_fail(w,h,"surface size overflow"),bytes=sv_size_mul_or_fail(pixels,4,"surface size overflow");SlugSurface *s=(SlugSurface*)sv_heap_alloc(sizeof(SlugSurface),SH_SURFACE);s->width=w;s->height=h;s->len=bytes;s->pixels=(unsigned char*)sv_xmalloc(bytes);memset(s->pixels,0,bytes);return sv_surface_value(s);}
static uint32_t sv_rgba(SlugValue v){uint64_t x=sv_nonnegative_integer(v,"RGBA color out of range");if(x>UINT32_MAX)sv_fail_kind("range","RGBA color out of range");return (uint32_t)x;}
static void sv_surface_pixel_raw(SlugSurface *s,int64_t x,int64_t y,uint32_t c){if(x<0||y<0||x>=s->width||y>=s->height)return;size_t i=((size_t)y*(size_t)s->width+(size_t)x)*4;s->pixels[i]=(unsigned char)(c>>24);s->pixels[i+1]=(unsigned char)(c>>16);s->pixels[i+2]=(unsigned char)(c>>8);s->pixels[i+3]=(unsigned char)c;}
static SlugValue sv_surface_pixel(SlugValue sv,SlugValue xv,SlugValue yv,SlugValue cv){SlugSurface *s=sv_require_surface(sv);int64_t x=sv_int_num(xv),y=sv_int_num(yv);if(x<0||y<0||x>=s->width||y>=s->height)sv_fail("pixel coordinate out of range");sv_surface_pixel_raw(s,x,y,sv_rgba(cv));return sv_null();}
static uint64_t sv_i64_abs_magnitude(int64_t x){return x<0?(uint64_t)(-(x+1))+1u:(uint64_t)x;}
static SlugValue sv_surface_rect(SlugValue sv,SlugValue xv,SlugValue yv,SlugValue wv,SlugValue hv,SlugValue cv){
    SlugSurface *s=sv_require_surface(sv);int64_t x=sv_signed_integer(xv,"rectangle x coordinate out of range"),y=sv_signed_integer(yv,"rectangle y coordinate out of range");size_t rw=sv_request_size(wv,"rectangle width out of range"),rh=sv_request_size(hv,"rectangle height out of range");uint32_t c=sv_rgba(cv);if(!rw||!rh)return sv_null();
    size_t sx=0,sy=0,dw=rw,dh=rh;
    if(x<0){uint64_t skip=sv_i64_abs_magnitude(x);if(skip>=(uint64_t)rw)return sv_null();dw=rw-(size_t)skip;}else{uint64_t ux=(uint64_t)x;if(ux>=(uint64_t)s->width)return sv_null();sx=(size_t)ux;}
    if(y<0){uint64_t skip=sv_i64_abs_magnitude(y);if(skip>=(uint64_t)rh)return sv_null();dh=rh-(size_t)skip;}else{uint64_t uy=(uint64_t)y;if(uy>=(uint64_t)s->height)return sv_null();sy=(size_t)uy;}
    size_t availw=s->width-sx,availh=s->height-sy;if(dw>availw)dw=availw;if(dh>availh)dh=availh;
    unsigned char px[4]={(unsigned char)(c>>24),(unsigned char)(c>>16),(unsigned char)(c>>8),(unsigned char)c};
    for(size_t yy=0;yy<dh;yy++){size_t base=((sy+yy)*s->width+sx)*4;for(size_t xx=0;xx<dw;xx++){size_t i=base+xx*4;memcpy(s->pixels+i,px,4);}}
    return sv_null();
}
static uint64_t sv_i64_distance(int64_t a,int64_t b){return a>=b?(uint64_t)a-(uint64_t)b:(uint64_t)b-(uint64_t)a;}
static SlugValue sv_surface_line(SlugValue sv,SlugValue x0v,SlugValue y0v,SlugValue x1v,SlugValue y1v,SlugValue cv){SlugSurface *s=sv_require_surface(sv);int64_t x0=sv_signed_integer(x0v,"line x coordinate out of range"),y0=sv_signed_integer(y0v,"line y coordinate out of range"),x1=sv_signed_integer(x1v,"line x coordinate out of range"),y1=sv_signed_integer(y1v,"line y coordinate out of range");uint32_t c=sv_rgba(cv);uint64_t dx=sv_i64_distance(x0,x1),dy=sv_i64_distance(y0,y1);int sx=x0<x1?1:-1,sy=y0<y1?1:-1;if(dx>=dy){uint64_t acc=dx/2;for(;;){sv_surface_pixel_raw(s,x0,y0,c);if(x0==x1)break;x0+=sx;if(dy&&acc>=dx-dy){acc-=dx-dy;y0+=sy;}else acc+=dy;}}else{uint64_t acc=dy/2;for(;;){sv_surface_pixel_raw(s,x0,y0,c);if(y0==y1)break;y0+=sy;if(dx&&acc>=dy-dx){acc-=dy-dx;x0+=sx;}else acc+=dx;}}return sv_null();}
static SlugValue sv_surface_bytes(SlugValue sv){SlugSurface *s=sv_require_surface(sv);return sv_bytes(s->pixels,s->len);}

static SlugWindow *sv_require_window(SlugValue v){if(v.tag!=SV_WINDOW||!v.as.window||v.as.window->closed)sv_fail("open window required");return v.as.window;}
#ifdef _WIN32
static LRESULT CALLBACK sv_window_proc(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp){(void)wp;(void)lp;if(msg==WM_CLOSE)return 0;return DefWindowProcW(hwnd,msg,wp,lp);}
static void sv_window_class(void){static bool done=false;if(done)return;WNDCLASSW wc;memset(&wc,0,sizeof(wc));wc.lpfnWndProc=sv_window_proc;wc.hInstance=GetModuleHandleW(NULL);wc.lpszClassName=L"SLUG_v017_Window";wc.hCursor=LoadCursor(NULL,IDC_ARROW);if(!RegisterClassW(&wc)&&GetLastError()!=ERROR_CLASS_ALREADY_EXISTS)sv_fail("window class registration failed");done=true;}
#endif
static SlugValue sv_window_new_value(SlugValue wv,SlugValue hv,SlugValue titlev){int64_t w=sv_int_num(wv),h=sv_int_num(hv);const char *title=sv_require_string(titlev,"window title must be string");if(w<=0||h<=0||w>INT_MAX||h>INT_MAX)sv_fail_kind("range","window dimensions outside host representability");
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
static SlugValue sv_audio_open_value(SlugValue ratev,SlugValue chv){uint64_t rate=sv_nonnegative_integer(ratev,"audio sample rate out of range"),ch=sv_nonnegative_integer(chv,"audio channel count out of range");if(!rate||!ch)sv_fail_kind("range","audio sample rate and channel count must be positive");
#ifndef _WIN32
(void)rate;(void)ch;sv_fail_kind("capability","audio capability unavailable on this platform");return sv_null();
#else
if(rate>UINT32_MAX||ch>UINT16_MAX)sv_fail_kind("range","audio format outside host representability");uint64_t block=ch*2u;if(block>UINT16_MAX)sv_fail_kind("range","audio frame size outside host representability");if(rate>UINT32_MAX/block)sv_fail_kind("range","audio byte rate outside host representability");WAVEFORMATEX fmt;memset(&fmt,0,sizeof(fmt));fmt.wFormatTag=WAVE_FORMAT_PCM;fmt.nChannels=(WORD)ch;fmt.nSamplesPerSec=(DWORD)rate;fmt.wBitsPerSample=16;fmt.nBlockAlign=(WORD)block;fmt.nAvgBytesPerSec=(DWORD)(rate*block);HWAVEOUT out=NULL;if(waveOutOpen(&out,WAVE_MAPPER,&fmt,0,0,CALLBACK_NULL)!=MMSYSERR_NOERROR)sv_fail_kind("capability","audio format/device unavailable");SlugAudio *a=(SlugAudio*)sv_heap_alloc(sizeof(SlugAudio),SH_AUDIO);a->closed=false;a->rate=(uint32_t)rate;a->channels=(uint16_t)ch;a->out=out;return sv_audio_value(a);
#endif
}
static SlugValue sv_audio_submit(SlugValue av,SlugValue bv){SlugAudio *a=sv_require_audio(av);if(bv.tag!=SV_BYTES||!bv.as.bytes)sv_fail_kind("type","audio submit requires bytes");size_t n=bv.as.bytes->len,frame=sv_size_mul_or_fail((size_t)a->channels,2,"audio frame size overflow");if(frame==0||n%frame!=0)sv_fail_kind("range","S16LE PCM length is not frame-aligned");
#ifndef _WIN32
(void)n;sv_fail_kind("capability","audio capability unavailable on this platform");return sv_null();
#else
size_t maxchunk=(size_t)UINT32_MAX-((size_t)UINT32_MAX%frame);if(!maxchunk)sv_fail_kind("range","audio frame exceeds backend buffer field");size_t off=0;while(off<n){size_t chunk=n-off;if(chunk>maxchunk)chunk=maxchunk;WAVEHDR h;memset(&h,0,sizeof(h));h.lpData=(LPSTR)(bv.as.bytes->data+off);h.dwBufferLength=(DWORD)chunk;if(waveOutPrepareHeader(a->out,&h,sizeof(h))!=MMSYSERR_NOERROR)sv_fail_kind("io","audio prepare failed");if(waveOutWrite(a->out,&h,sizeof(h))!=MMSYSERR_NOERROR){waveOutUnprepareHeader(a->out,&h,sizeof(h));sv_fail_kind("io","audio submit failed");}while(!(h.dwFlags&WHDR_DONE))Sleep(1);while(waveOutUnprepareHeader(a->out,&h,sizeof(h))==WAVERR_STILLPLAYING)Sleep(1);off+=chunk;}return sv_null();
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
default:sv_fail_kind("capability","serial baud unsupported by host backend");return B9600;}}
#endif
static SlugValue sv_serial_open_value(SlugValue pathv,SlugValue baudv){const char *path=sv_require_string(pathv,"serial path must be string");uint64_t baud=sv_nonnegative_integer(baudv,"serial baud out of range");SlugDevice *d=sv_device_alloc();
#ifdef _WIN32
if(baud>UINT32_MAX)sv_fail_kind("range","serial baud outside host representability");wchar_t *wp=sv_widen(path);d->h=CreateFileW(wp,GENERIC_READ|GENERIC_WRITE,0,NULL,OPEN_EXISTING,0,NULL);free(wp);if(d->h==INVALID_HANDLE_VALUE)sv_fail_kind("io","serial open failed");DCB dc;memset(&dc,0,sizeof(dc));dc.DCBlength=sizeof(dc);if(!GetCommState(d->h,&dc))sv_fail("serial configuration failed");dc.BaudRate=(DWORD)baud;dc.ByteSize=8;dc.Parity=NOPARITY;dc.StopBits=ONESTOPBIT;dc.fBinary=TRUE;dc.fParity=FALSE;if(!SetCommState(d->h,&dc))sv_fail("serial configuration failed");COMMTIMEOUTS to={0};to.ReadIntervalTimeout=MAXDWORD;to.ReadTotalTimeoutConstant=100;SetCommTimeouts(d->h,&to);
#else
d->fd=open(path,O_RDWR|O_NOCTTY);if(d->fd<0)sv_fail("serial open failed");struct termios t;if(tcgetattr(d->fd,&t)!=0)sv_fail("serial configuration failed");speed_t sp=sv_serial_speed(baud);if(cfsetispeed(&t,sp)!=0||cfsetospeed(&t,sp)!=0)sv_fail("serial configuration failed");t.c_cflag&=~(PARENB|CSTOPB|CSIZE);t.c_cflag|=CS8|CLOCAL|CREAD;t.c_iflag&=~(IXON|IXOFF|IXANY);t.c_lflag&=~(ICANON|ECHO|ECHOE|ISIG);t.c_oflag&=~OPOST;t.c_cc[VMIN]=0;t.c_cc[VTIME]=1;if(tcsetattr(d->fd,TCSANOW,&t)!=0)sv_fail("serial configuration failed");
#endif
return sv_device_value(d);}
static SlugValue sv_device_read_value(SlugValue dv,SlugValue nv){SlugDevice *d=sv_require_device(dv);size_t requested=sv_request_size(nv,"device read length out of range");size_t n=requested;const size_t soft_chunk=1024u*1024u;if(n>soft_chunk)n=soft_chunk;
#ifdef _WIN32
if(n>(size_t)UINT32_MAX)n=UINT32_MAX;
#endif
unsigned char *buf=n?(unsigned char*)sv_xmalloc(n):NULL;size_t got=0;
#ifdef _WIN32
DWORD r=0;if(n&&!ReadFile(d->h,buf,(DWORD)n,&r,NULL)){free(buf);sv_fail_kind("io","device read failed");}got=(size_t)r;
#else
ssize_t r;do{r=n?read(d->fd,buf,n):0;}while(r<0&&errno==EINTR);if(r<0){free(buf);sv_fail_kind("io","device read failed");}got=(size_t)r;
#endif
SlugValue out=sv_bytes(buf,got);free(buf);return out;}
static SlugValue sv_device_write_value(SlugValue dv,SlugValue bv){SlugDevice *d=sv_require_device(dv);if(bv.tag!=SV_BYTES||!bv.as.bytes)sv_fail_kind("type","device write requires bytes");const unsigned char *p=bv.as.bytes->data;size_t n=bv.as.bytes->len,wrote=0;while(wrote<n){
#ifdef _WIN32
DWORD chunk=(DWORD)((n-wrote)>UINT32_MAX?UINT32_MAX:(n-wrote)),r=0;if(!WriteFile(d->h,p+wrote,chunk,&r,NULL)||r==0)sv_fail_kind("io","device write failed");wrote+=(size_t)r;
#else
size_t chunk=n-wrote;
#ifdef SSIZE_MAX
if(chunk>(size_t)SSIZE_MAX)chunk=(size_t)SSIZE_MAX;
#endif
ssize_t r=write(d->fd,p+wrote,chunk);if(r<0&&errno==EINTR)continue;if(r<=0)sv_fail_kind("io","device write failed");wrote+=(size_t)r;
#endif
}return sv_size_value(wrote);}
static SlugValue sv_device_close_value(SlugValue dv){if(dv.tag!=SV_DEVICE||!dv.as.device)sv_fail("device required");sv_device_close_raw(dv.as.device);return sv_null();}

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

'''


def _c_string(s: str) -> str:
    # Clang/MSVC accept UTF-8 source; keep Unicode intact instead of emitting JSON
    # surrogate escapes, which are not valid C universal-character names.
    return json.dumps(s, ensure_ascii=False)


def _c_slug_string(s: str) -> str:
    """Length-aware UTF-8 SLUG string literal, including embedded NUL bytes."""
    data = s.encode("utf-8")
    # Three-digit octal escapes have a fixed lexical width in C, unlike \x escapes.
    literal = '"' + ''.join(f"\\{byte:03o}" for byte in data) + '"'
    return f"sv_string_n((const unsigned char*){literal}, {len(data)})"


@dataclass
class _CGScope:
    active: dict[str, str]
    pending: dict[str, str]
    frame: str | None = None
    contracts: dict[str, str | None] = field(default_factory=dict)


@dataclass
class CGenerator:
    program: ast.Program
    ir: IRModule | None = None
    optimization: OptimizerResult | None = None

    def __post_init__(self) -> None:
        if self.ir is None:
            self.ir = lower_ir(self.program)
        if self.optimization is None:
            self.optimization = optimize_mir(lower_mir(self.ir))
        self.optimizer_constants = self.optimization.constants_by_source
        self.optimizer_elidable_sources = self.optimization.elidable_sources
        self.assignment_contracts = self.ir.assignment_contracts
        self.temp_id = 0
        self.name_id = 0
        self.scopes: list[_CGScope] = []
        self.functions: dict[str, ast.FunctionDecl] = {
            s.name: s for s in self.program.statements if isinstance(s, ast.FunctionDecl)
        }
        self.reachable_functions = self._find_reachable_functions()
        self.current_function: ast.FunctionDecl | None = None
        self.globals: dict[str, str] = {}
        for name in sorted(self._direct_defs(self.program.statements)):
            self.globals[name] = self._new_cvar("g_" + name)
        self.global_contracts = self._direct_contracts(self.program.statements)
        self.classes: dict[str, ast.ClassDecl] = {
            s.name: s for s in self.program.statements if isinstance(s, ast.ClassDecl)
        }
        self.class_ids: dict[str, int] = {name: i + 1 for i, name in enumerate(self.classes)}
        self.class_methods: dict[str, dict[tuple[bool, str], ast.FunctionDecl]] = {}
        self.class_destructors: dict[str, ast.DestructorDecl | None] = {}
        self.static_fields: dict[tuple[str, str], str] = {}
        self.field_decls: dict[str, dict[tuple[bool, str], tuple[ast.MemberExpr, ast.Expr, bool]]] = {}
        for cname, cls in self.classes.items():
            methods: dict[tuple[bool, str], ast.FunctionDecl] = {}
            fields: dict[tuple[bool, str], tuple[ast.MemberExpr, ast.Expr, bool]] = {}
            dtor = None
            for child in cls.body:
                if isinstance(child, ast.FunctionDecl):
                    methods[(child.static, child.name)] = child
                elif isinstance(child, ast.DestructorDecl):
                    dtor = child
                elif isinstance(child, ast.ExprStmt) and isinstance(child.expr, ast.SetMemberExpr):
                    t = child.expr.target
                    if t.base is None and t.class_name is None:
                        fields[(t.static, t.name)] = (t, child.expr.value, child.expr.immutable)
                elif isinstance(child, ast.SetMemberStmt) and child.define:
                    t = child.target
                    if t.base is None and t.class_name is None:
                        fields[(t.static, t.name)] = (t, child.value, child.immutable)
            self.class_methods[cname] = methods
            self.class_destructors[cname] = dtor
            self.field_decls[cname] = fields
            for (static, fname), _ in fields.items():
                if static:
                    self.static_fields[(cname, fname)] = self._new_cvar(f"static_{cname}_{fname}")
        self.current_class: str | None = None
        self.current_self: str | None = None
        self.current_static_method = False
        self.current_mode: str | None = None
        self.lambda_ids: dict[int, int] = {}
        self.lambda_nodes: dict[int, ast.LambdaExpr] = {}
        self.lambda_specs: dict[int, tuple[tuple[str, ...], tuple[str | None, ...], str | None, bool, bool]] = {}
        self._collect_lambda_ids(self.program)
        self.try_stack: list[dict[str, object]] = []
        self.catch_error_stack: list[str] = []
        self.cg_loop_depth = 0
        self.function_scope_frame: str | None = None
        self.loop_scope_frames: list[str] = []
        self._expr_flat_lines: list[str] | None = None

    def _collect_lambda_ids(self, node: object) -> None:
        if isinstance(node, ast.LambdaExpr):
            key=id(node)
            if key not in self.lambda_ids:
                lid=len(self.lambda_ids)+1;self.lambda_ids[key]=lid;self.lambda_nodes[lid]=node
        if isinstance(node, ast.Node):
            for f in fields(node):
                self._collect_lambda_ids(getattr(node,f.name))
        elif isinstance(node, (tuple,list)):
            for x in node:self._collect_lambda_ids(x)
        elif isinstance(node, dict):
            for x in node.values():self._collect_lambda_ids(x)

    def _new_cvar(self, name: str) -> str:
        self.name_id += 1
        safe = "".join(c if c.isalnum() else "_" for c in name)
        return f"v_{safe}_{self.name_id}"

    def _fn_cname(self, name: str) -> str:
        return "slug_fn_" + name

    def _lambda_cname(self, lid: int) -> str:
        return f"slug_lambda_{lid}"

    def _ctor_cname(self, cls: str) -> str:
        return "slug_ctor_" + cls

    def _init_cname(self, cls: str) -> str:
        return "slug_init_" + cls

    def _method_cname(self, cls: str, name: str, static: bool = False) -> str:
        return ("slug_sm_" if static else "slug_m_") + cls + "_" + name

    def _dispatch_cname(self, name: str) -> str:
        return "slug_dispatch_" + name

    def _dtor_cname(self, cls: str) -> str:
        return "slug_dtor_" + cls

    def _lookup_method_owner(self, cls: str, name: str, static: bool) -> tuple[str, ast.FunctionDecl] | None:
        cur: str | None = cls
        while cur is not None:
            fn = self.class_methods.get(cur, {}).get((static, name))
            if fn is not None:
                return cur, fn
            parent = self.classes.get(cur).parent if cur in self.classes else None
            cur = parent
        return None

    def _static_field_var(self, cls: str, name: str) -> str:
        cur: str | None = cls
        while cur is not None:
            key = (cur, name)
            if key in self.static_fields:
                return self.static_fields[key]
            # static fields intentionally do not inherit; this loop is only defensive.
            break
        raise CodegenError(f"unknown static field {cls}.{name}")

    def _self_value(self) -> str:
        if self.current_self is None:
            raise CodegenError("current instance used outside instance context")
        return f"sv_object_value({self.current_self})"

    def _calls_in_expr(self, e: ast.Expr, out: set[str]) -> None:
        if isinstance(e, ast.FormattedString):
            for part in e.parts:
                if not isinstance(part, str): self._calls_in_expr(part,out)
        elif isinstance(e, ast.Call):
            if e.name in self.functions: out.add(e.name)
            for a in e.args: self._calls_in_expr(a,out)
        elif isinstance(e, ast.CallableInvoke):
            self._calls_in_expr(e.callee,out)
            for a in e.args:self._calls_in_expr(a,out)
        elif isinstance(e, ast.LambdaExpr):
            for p in e.params:
                if p.default is not None:self._calls_in_expr(p.default,out)
            self._calls_in_stmts(e.body,out)
        elif isinstance(e, ast.ClassCall):
            for a in e.args:self._calls_in_expr(a,out)
        elif isinstance(e, ast.Cast): self._calls_in_expr(e.value,out)
        elif isinstance(e, ast.DynamicCast): self._calls_in_expr(e.type_expr,out);self._calls_in_expr(e.value,out)
        elif isinstance(e, ast.Unary): self._calls_in_expr(e.value,out)
        elif isinstance(e, ast.Binary): self._calls_in_expr(e.left,out);self._calls_in_expr(e.right,out)
        elif isinstance(e, ast.AssignExpr): self._calls_in_expr(e.value,out)
        elif isinstance(e, ast.BoolExpr): self._calls_in_expr(e.value,out)
        elif isinstance(e, ast.Compare): self._calls_in_expr(e.left,out);self._calls_in_expr(e.right,out)
        elif isinstance(e, ast.LogicNot): self._calls_in_expr(e.value,out)
        elif isinstance(e, ast.LogicBinary): self._calls_in_expr(e.left,out);self._calls_in_expr(e.right,out)
        elif isinstance(e, ast.ListLiteral):
            for x in e.items:self._calls_in_expr(x,out)
        elif isinstance(e, ast.MapLiteral):
            for k,v in e.entries:self._calls_in_expr(k,out);self._calls_in_expr(v,out)
        elif isinstance(e, ast.IndexExpr):self._calls_in_expr(e.base,out);self._calls_in_expr(e.index,out)
        elif isinstance(e, ast.SliceExpr):
            self._calls_in_expr(e.base,out)
            for x in (e.start,e.stop,e.step):
                if x is not None:self._calls_in_expr(x,out)
        elif isinstance(e, ast.SetIndexExpr):self._calls_in_expr(e.target,out);self._calls_in_expr(e.value,out)
        elif isinstance(e, ast.MemberExpr):
            if e.base is not None:self._calls_in_expr(e.base,out)
        elif isinstance(e, ast.MethodCall):
            if e.receiver is not None:self._calls_in_expr(e.receiver,out)
            for a in e.args:self._calls_in_expr(a,out)
        elif isinstance(e, ast.SetMemberExpr):self._calls_in_expr(e.target,out);self._calls_in_expr(e.value,out)

    def _calls_in_stmts(self, stmts: tuple[ast.Stmt,...], out:set[str]) -> None:
        for s in stmts:
            if isinstance(s,ast.ExprStmt):self._calls_in_expr(s.expr,out)
            elif isinstance(s,ast.AssignStmt):self._calls_in_expr(s.value,out)
            elif isinstance(s,ast.SetIndexStmt):self._calls_in_expr(s.target,out);self._calls_in_expr(s.value,out)
            elif isinstance(s,ast.SetMemberStmt):self._calls_in_expr(s.target,out);self._calls_in_expr(s.value,out)
            elif isinstance(s,ast.SuperInitStmt):
                for a in s.args:self._calls_in_expr(a,out)
            elif isinstance(s,ast.DestructorDecl):self._calls_in_stmts(s.body,out)
            elif isinstance(s,ast.MutateStmt):self._calls_in_expr(s.target,out)
            elif isinstance(s,ast.ReturnStmt):
                for v in s.values:self._calls_in_expr(v,out)
            elif isinstance(s,ast.IfStmt):
                self._calls_in_expr(s.condition,out);self._calls_in_stmts(s.body,out)
                for c,b in s.elifs:self._calls_in_expr(c,out);self._calls_in_stmts(b,out)
                if s.else_body:self._calls_in_stmts(s.else_body,out)
            elif isinstance(s,ast.WhileStmt):self._calls_in_expr(s.condition,out);self._calls_in_stmts(s.body,out)
            elif isinstance(s,ast.ForStmt):
                for e in (s.source,s.start,s.stop,s.step):
                    if e is not None:self._calls_in_expr(e,out)
                self._calls_in_stmts(s.body,out)
            elif isinstance(s,ast.RaiseStmt):
                if s.value is not None:self._calls_in_expr(s.value,out)
            elif isinstance(s,ast.TryStmt):
                self._calls_in_stmts(s.body,out)
                if s.catch_body:self._calls_in_stmts(s.catch_body,out)
                if s.finally_body:self._calls_in_stmts(s.finally_body,out)

    def _find_reachable_functions(self) -> set[str]:
        used:set[str]=set()
        top=tuple(s for s in self.program.statements if not isinstance(s,(ast.FunctionDecl,ast.ClassDecl,ast.InterfaceDecl)))
        self._calls_in_stmts(top,used)
        # Class constructor bodies, methods and destructors may call module functions.
        # Treat those references as roots because class methods are dynamically callable.
        for cls in (s for s in self.program.statements if isinstance(s,ast.ClassDecl)):
            ctor=tuple(x for x in cls.body if not isinstance(x,ast.FunctionDecl))
            self._calls_in_stmts(ctor,used)
            for x in cls.body:
                if isinstance(x,ast.FunctionDecl):self._calls_in_stmts(x.body,used)
                elif isinstance(x,ast.DestructorDecl):self._calls_in_stmts(x.body,used)
        queue=list(used)
        while queue:
            name=queue.pop()
            fn=self.functions.get(name)
            if fn is None:continue
            nested:set[str]=set();self._calls_in_stmts(fn.body,nested)
            for n in nested:
                if n not in used:
                    used.add(n);queue.append(n)
        return used

    def _expr_defs(self, e: ast.Expr, out: set[str]) -> None:
        if isinstance(e, ast.FormattedString):
            for part in e.parts:
                if not isinstance(part, str): self._expr_defs(part,out)
        elif isinstance(e, ast.AssignExpr):
            out.update(e.targets); self._expr_defs(e.value, out)
        elif isinstance(e, ast.SetIndexExpr):
            self._expr_defs(e.target, out); self._expr_defs(e.value, out)
        elif isinstance(e, (ast.Call, ast.ClassCall)):
            for a in e.args: self._expr_defs(a, out)
        elif isinstance(e, ast.CallableInvoke):
            self._expr_defs(e.callee, out)
            for a in e.args: self._expr_defs(a, out)
        elif isinstance(e, ast.LambdaExpr):
            for p in e.params:
                if p.default is not None:self._expr_defs(p.default,out)
        elif isinstance(e, ast.Cast): self._expr_defs(e.value, out)
        elif isinstance(e, ast.DynamicCast): self._expr_defs(e.type_expr, out); self._expr_defs(e.value, out)
        elif isinstance(e, ast.Unary): self._expr_defs(e.value, out)
        elif isinstance(e, ast.Binary): self._expr_defs(e.left, out); self._expr_defs(e.right, out)
        elif isinstance(e, ast.BoolExpr): self._expr_defs(e.value, out)
        elif isinstance(e, ast.Compare): self._expr_defs(e.left, out); self._expr_defs(e.right, out)
        elif isinstance(e, ast.LogicNot): self._expr_defs(e.value, out)
        elif isinstance(e, ast.LogicBinary): self._expr_defs(e.left, out); self._expr_defs(e.right, out)
        elif isinstance(e, ast.ListLiteral):
            for i in e.items: self._expr_defs(i, out)
        elif isinstance(e, ast.MapLiteral):
            for k,v in e.entries: self._expr_defs(k,out); self._expr_defs(v,out)
        elif isinstance(e, ast.IndexExpr): self._expr_defs(e.base,out); self._expr_defs(e.index,out)
        elif isinstance(e, ast.SliceExpr):
            self._expr_defs(e.base,out)
            for part in (e.start,e.stop,e.step):
                if part is not None: self._expr_defs(part,out)
        elif isinstance(e, ast.MemberExpr):
            if e.base is not None:self._expr_defs(e.base,out)
        elif isinstance(e, ast.MethodCall):
            if e.receiver is not None:self._expr_defs(e.receiver,out)
            for a in e.args:self._expr_defs(a,out)
        elif isinstance(e, ast.SetMemberExpr):self._expr_defs(e.target,out);self._expr_defs(e.value,out)

    def _direct_defs(self, stmts: tuple[ast.Stmt, ...], forced: tuple[str, ...] = ()) -> set[str]:
        out = set(forced)
        for s in stmts:
            if isinstance(s, ast.AssignStmt): out.update(s.targets); self._expr_defs(s.value, out)
            elif isinstance(s, ast.SetIndexStmt): self._expr_defs(s.target,out); self._expr_defs(s.value,out)
            elif isinstance(s, ast.SetMemberStmt): self._expr_defs(s.target,out); self._expr_defs(s.value,out)
            elif isinstance(s, ast.SuperInitStmt):
                for a in s.args:self._expr_defs(a,out)
            elif isinstance(s, ast.ExprStmt): self._expr_defs(s.expr, out)
            elif isinstance(s, ast.ReturnStmt):
                for v in s.values: self._expr_defs(v, out)
            elif isinstance(s, ast.IfStmt):
                self._expr_defs(s.condition, out)
                for c,_ in s.elifs:self._expr_defs(c,out)
            elif isinstance(s, ast.WhileStmt): self._expr_defs(s.condition,out)
            elif isinstance(s, ast.ForStmt):
                for e in (s.source,s.start,s.stop,s.step):
                    if e is not None:self._expr_defs(e,out)
            elif isinstance(s, ast.RaiseStmt):
                if s.value is not None:self._expr_defs(s.value,out)
        return out

    def _expr_contract_defs(self, e: ast.Expr, out: dict[str, str | None]) -> None:
        if isinstance(e, ast.FormattedString):
            for part in e.parts:
                if not isinstance(part, str): self._expr_contract_defs(part,out)
        elif isinstance(e, ast.AssignExpr):
            types=e.target_types if e.target_types else (None,)*len(e.targets)
            for n,t in zip(e.targets,types):
                if t is not None: out[n]=t
            self._expr_contract_defs(e.value,out)
        elif isinstance(e, ast.SetIndexExpr): self._expr_contract_defs(e.value,out)
        elif isinstance(e, (ast.Call, ast.ClassCall)):
            for a in e.args:self._expr_contract_defs(a,out)
        elif isinstance(e, ast.CallableInvoke):
            self._expr_contract_defs(e.callee,out)
            for a in e.args:self._expr_contract_defs(a,out)
        elif isinstance(e, ast.LambdaExpr):
            for p in e.params:
                if p.default is not None:self._expr_contract_defs(p.default,out)
        elif isinstance(e, ast.Cast): self._expr_contract_defs(e.value,out)
        elif isinstance(e, ast.DynamicCast): self._expr_contract_defs(e.type_expr,out);self._expr_contract_defs(e.value,out)
        elif isinstance(e, ast.Unary): self._expr_contract_defs(e.value,out)
        elif isinstance(e, ast.Binary): self._expr_contract_defs(e.left,out);self._expr_contract_defs(e.right,out)
        elif isinstance(e, ast.BoolExpr): self._expr_contract_defs(e.value,out)
        elif isinstance(e, ast.Compare): self._expr_contract_defs(e.left,out);self._expr_contract_defs(e.right,out)
        elif isinstance(e, ast.LogicNot): self._expr_contract_defs(e.value,out)
        elif isinstance(e, ast.LogicBinary): self._expr_contract_defs(e.left,out);self._expr_contract_defs(e.right,out)
        elif isinstance(e, ast.ListLiteral):
            for x in e.items:self._expr_contract_defs(x,out)
        elif isinstance(e, ast.MapLiteral):
            for k,v in e.entries:self._expr_contract_defs(k,out);self._expr_contract_defs(v,out)
        elif isinstance(e, ast.IndexExpr): self._expr_contract_defs(e.base,out);self._expr_contract_defs(e.index,out)
        elif isinstance(e, ast.SliceExpr):
            self._expr_contract_defs(e.base,out)
            for x in (e.start,e.stop,e.step):
                if x is not None:self._expr_contract_defs(x,out)
        elif isinstance(e, ast.MemberExpr):
            if e.base is not None:self._expr_contract_defs(e.base,out)
        elif isinstance(e, ast.MethodCall):
            if e.receiver is not None:self._expr_contract_defs(e.receiver,out)
            for a in e.args:self._expr_contract_defs(a,out)
        elif isinstance(e, ast.SetMemberExpr): self._expr_contract_defs(e.value,out)

    def _direct_contracts(self, stmts: tuple[ast.Stmt, ...]) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for st in stmts:
            if isinstance(st, ast.AssignStmt):
                types=st.target_types if st.target_types else (None,)*len(st.targets)
                for n,t in zip(st.targets,types):
                    if t is not None:out[n]=t
                self._expr_contract_defs(st.value,out)
            elif isinstance(st, ast.ExprStmt):self._expr_contract_defs(st.expr,out)
            elif isinstance(st, ast.SetIndexStmt):self._expr_contract_defs(st.value,out)
            elif isinstance(st, ast.SetMemberStmt):self._expr_contract_defs(st.value,out)
            elif isinstance(st, ast.SuperInitStmt):
                for a in st.args:self._expr_contract_defs(a,out)
            elif isinstance(st, ast.ReturnStmt):
                for v in st.values:self._expr_contract_defs(v,out)
            elif isinstance(st, ast.IfStmt):
                self._expr_contract_defs(st.condition,out)
                for c,_ in st.elifs:self._expr_contract_defs(c,out)
            elif isinstance(st, ast.WhileStmt):self._expr_contract_defs(st.condition,out)
            elif isinstance(st, ast.ForStmt):
                for e in (st.source,st.start,st.stop,st.step):
                    if e is not None:self._expr_contract_defs(e,out)
            elif isinstance(st, ast.RaiseStmt):
                if st.value is not None:self._expr_contract_defs(st.value,out)
        return out

    @staticmethod
    def _lambda_referenced_names(node: object, out: set[str] | None = None) -> set[str]:
        """Conservative lexical names a lambda (including nested lambdas) may need.

        Over-capturing is safe; under-capturing is not. Globals are filtered later.
        """
        out = out if out is not None else set()
        if isinstance(node, (ast.Var, ast.ExtendedName)):
            out.add(node.name)
            return out
        if isinstance(node, ast.AssignStmt):
            out.update(node.targets)
        if isinstance(node, ast.AssignExpr) and node.op == "=":
            out.update(node.targets)
        if isinstance(node, ast.Node):
            for f in fields(node):
                CGenerator._lambda_referenced_names(getattr(node, f.name), out)
        elif isinstance(node, (tuple, list)):
            for value in node:
                CGenerator._lambda_referenced_names(value, out)
        elif isinstance(node, dict):
            for value in node.values():
                CGenerator._lambda_referenced_names(value, out)
        return out

    @classmethod
    def _captured_names_in(cls, node: object, out: set[str] | None = None) -> set[str]:
        out = out if out is not None else set()
        if isinstance(node, ast.LambdaExpr):
            out.update(cls._lambda_referenced_names(node.body))
            for param in node.params:
                if param.default is not None:
                    out.update(cls._lambda_referenced_names(param.default))
            return out
        if isinstance(node, ast.Node):
            for f in fields(node):
                cls._captured_names_in(getattr(node, f.name), out)
        elif isinstance(node, (tuple, list)):
            for value in node:
                cls._captured_names_in(value, out)
        elif isinstance(node, dict):
            for value in node.values():
                cls._captured_names_in(value, out)
        return out

    def _push_scope(self, stmts: tuple[ast.Stmt, ...], forced: tuple[str, ...] = (), forced_contracts: dict[str,str|None] | None = None) -> list[str]:
        names=sorted(self._direct_defs(stmts,forced)); pending={n:self._new_cvar(n) for n in names}
        scope_name=self._new_cvar("scope")
        contracts=self._direct_contracts(stmts);contracts.update(forced_contracts or {})
        frame=_CGScope({},pending,scope_name,contracts);self.scopes.append(frame)
        lines=[f"SlugScopeFrame {scope_name};", f"sv_scope_enter(&{scope_name});"]
        # v1.0 release invariant: lexical cells are heap-backed.  C setjmp/longjmp
        # can make modified automatic objects indeterminate after a jump; keeping
        # cells managed avoids that class of backend UB.  A later optimizer may
        # stack-promote cells only after proving they cannot cross an exception edge.
        for n in names:
            cell=pending[n]
            lines.append(f"SlugCell *{cell} = sv_cell_new();")
        for n in forced:frame.active[n]=pending[n]
        return lines

    def _push_root_scope(self) -> None:
        self.scopes.append(_CGScope(dict(self.globals), {}, None, dict(self.global_contracts)))

    def _pop_scope(self)->None:self.scopes.pop()

    def _current_scope_frame(self) -> str:
        if not self.scopes or self.scopes[-1].frame is None:
            raise CodegenError("runtime lexical scope frame is unavailable")
        return self.scopes[-1].frame

    @classmethod
    def _expr_gc_neutral(cls, e: ast.Expr) -> bool:
        """True only when evaluating *e* cannot change managed reachability.

        This proof is intentionally tiny.  It licenses removal of an otherwise
        redundant statement-boundary tracing pass; it does *not* imply general
        purity (``co`` may still perform I/O).  Anything that allocates a tracked
        value, mutates a binding/container/object, invokes user code, or has unknown
        effects keeps the collection safe point.
        """
        if isinstance(e, (ast.Var, ast.ExtendedName, ast.DefaultArg)):
            return True
        if isinstance(e, ast.Literal):
            return e.kind not in {"string"}
        if isinstance(e, ast.FormattedString):
            return False
        if isinstance(e, ast.Cast):
            return not e.type_code.startswith("s") and cls._expr_gc_neutral(e.value)
        if isinstance(e, ast.DynamicCast):
            return False
        if isinstance(e, ast.Unary):
            return cls._expr_gc_neutral(e.value)
        if isinstance(e, ast.Binary):
            return cls._expr_gc_neutral(e.left) and cls._expr_gc_neutral(e.right)
        if isinstance(e, ast.BoolExpr):
            return cls._expr_gc_neutral(e.value)
        if isinstance(e, ast.LogicNot):
            return cls._expr_gc_neutral(e.value)
        if isinstance(e, ast.LogicBinary):
            return cls._expr_gc_neutral(e.left) and cls._expr_gc_neutral(e.right)
        if isinstance(e, ast.Compare):
            return cls._expr_gc_neutral(e.left) and cls._expr_gc_neutral(e.right)
        if isinstance(e, ast.IndexExpr):
            return cls._expr_gc_neutral(e.base) and cls._expr_gc_neutral(e.index)
        if isinstance(e, ast.MemberExpr):
            return e.base is None or cls._expr_gc_neutral(e.base)
        if isinstance(e, ast.Call) and e.name in {"co", "ln", "in", "iv"}:
            return all(cls._expr_gc_neutral(a) for a in e.args)
        return False

    def _stmt_gc(self, s: ast.Stmt, depth: int) -> list[str]:
        p="    "*depth
        out=self._stmt(s,depth)
        if isinstance(s,(ast.FunctionDecl,ast.ClassDecl,ast.InterfaceDecl,ast.CommentStmt,ast.ImportStmt,ast.NamespaceStmt)):
            return out
        if isinstance(s, ast.ExprStmt) and self._expr_gc_neutral(s.expr):
            out.append(p+"/* GC safe point elided: expression cannot change managed reachability. */")
            return out
        out.append(p+"sv_gc_safepoint();")
        return out

    def _resolve_cell(self,name:str)->str|None:
        for scope in reversed(self.scopes):
            if name in scope.active:return scope.active[name]
        return self.globals.get(name)

    def _resolve(self,name:str)->str|None:
        cell=self._resolve_cell(name)
        return None if cell is None else f"({cell})->value"

    def _binding_contract(self,name:str,current:bool=False)->str|None:
        if current and self.scopes:
            return self.scopes[-1].contracts.get(name)
        for scope in reversed(self.scopes):
            if name in scope.active:
                return scope.contracts.get(name)
        if name in self.globals:
            return self.global_contracts.get(name)
        # If no binding is active, nearest-scope `=` creates in the current scope.
        return self.scopes[-1].contracts.get(name) if self.scopes else self.global_contracts.get(name)

    def _define_current(self,name:str)->str:
        scope=self.scopes[-1]
        if name not in scope.active:
            if name not in scope.pending:scope.pending[name]=self._new_cvar(name)
            scope.active[name]=scope.pending[name]
        return f"({scope.active[name]})->value"

    def _visible_capture_cells(self, node: ast.LambdaExpr) -> tuple[tuple[str, str], ...]:
        needed=self._lambda_referenced_names(node.body)
        for param in node.params:
            if param.default is not None:
                needed.update(self._lambda_referenced_names(param.default))
        seen: set[str] = set(); out: list[tuple[str,str]] = []
        for scope in reversed(self.scopes):
            for name, cell in scope.active.items():
                if name in seen:
                    continue
                seen.add(name)
                if self.globals.get(name) == cell or name not in needed:
                    continue
                out.append((name, cell))
        return tuple(out)

    def _lambda_expr(self, e: ast.LambdaExpr) -> str:
        lid=self.lambda_ids[id(e)]
        pairs=self._visible_capture_cells(e)
        names=tuple(n for n,_ in pairs)
        capture_contracts=tuple(self._binding_contract(n,False) for n in names)
        has_self=self.current_self is not None
        spec=(names,capture_contracts,self.current_class,has_self,self.current_static_method)
        old=self.lambda_specs.get(lid)
        if old is not None and old!=spec:
            raise CodegenError("lambda capture environment changed across one lexical site")
        self.lambda_specs[lid]=spec
        cells=[c for _,c in pairs]
        if has_self:
            cells.append(f"sv_cell_from(sv_object_value({self.current_self}))")
        arr="NULL" if not cells else "(SlugCell*[]){"+", ".join(cells)+"}"
        return f"sv_callable_value(sv_closure_new({self._lambda_cname(lid)}, {len(cells)}, {arr}))"

    def _lambda_def(self, lid: int) -> list[str]:
        e=self.lambda_nodes[lid]
        names,capture_contracts,cname,has_self,static_ctx=self.lambda_specs[lid]
        saved_scopes=self.scopes; saved_fn=self.current_function; saved_root=self.function_scope_frame; saved_loops=self.loop_scope_frames
        saved_class,saved_self,saved_static,saved_mode=self.current_class,self.current_self,self.current_static_method,self.current_mode
        self.scopes=[];self.current_function=e;self.current_class=cname;self.current_static_method=static_ctx;self.current_mode="lambda";self.loop_scope_frames=[]
        active={name:f"closure->captures[{i}]" for i,name in enumerate(names)}
        self.scopes.append(_CGScope(active,{},None,dict(zip(names,capture_contracts))))
        if has_self:
            self.current_self=f"sv_as_object(closure->captures[{len(names)}]->value)"
        else:
            self.current_self=None
        forced=tuple(p.name for p in e.params)+((e.variadic,) if e.variadic else ())
        out=[f"static SlugResult {self._lambda_cname(lid)}(SlugClosure *closure, size_t argc, SlugValue *argv){{"]
        decls=self._push_scope(e.body,forced,{p.name:p.type_code for p in e.params});root=self._current_scope_frame();self.function_scope_frame=root;out.extend("    "+d for d in decls)
        out.append("    (void)sv_cell_from(sv_callable_value(closure));")
        out.extend(self._emit_param_bindings(e.params,e.variadic,f"lambda {lid}",1))
        for child in e.body:out.extend(self._stmt_gc(child,1))
        out.append(f"    sv_scope_leave(&{root});");out.append("    return sv_result0();");out.append("}")
        self._pop_scope();self._pop_scope();self.scopes=saved_scopes;self.current_function=saved_fn;self.function_scope_frame=saved_root;self.loop_scope_frames=saved_loops
        self.current_class,self.current_self,self.current_static_method,self.current_mode=saved_class,saved_self,saved_static,saved_mode
        return out

    def _cast_expr(self, type_code: str, value: str) -> str:
        base=type_code[0]
        width=type_code[1:]
        if base=="i":
            return f"sv_cast_i_width({value}, {int(width) if width else 64})"
        if base=="u":
            return f"sv_cast_u_width({value}, {int(width) if width else 64})"
        fn={"f":"sv_cast_f","s":"sv_cast_s","b":"sv_cast_b"}[base]
        return f"{fn}({value})"

    def _contract_expr(self, type_code: str, value: str) -> str:
        base=type_code[0]
        width=type_code[1:]
        if base=="i":
            return f"sv_contract_i_width({value}, {int(width) if width else 64})"
        if base=="u":
            return f"sv_contract_u_width({value}, {int(width) if width else 64})"
        fn={"f":"sv_contract_f","s":"sv_contract_s","b":"sv_contract_b"}[base]
        return f"{fn}({value})"

    def _materialize_expr(self, code: str) -> str:
        """Materialize one value in the active flat-expression lowering context.

        The temporary is rooted until the surrounding source expression has consumed
        it. This converts recursive C expression trees into a flat sequence without
        changing SLUG's left-to-right evaluation or GC reachability.
        """
        if self._expr_flat_lines is None:
            return code
        self.temp_id += 1
        tmp = f"_slug_expr_{self.temp_id}"
        self._expr_flat_lines.append(f"SlugValue {tmp} = {code};")
        self._expr_flat_lines.append(f"(void)sv_temp_root_push({tmp});")
        return tmp

    def _flat_expr_capture(self, build) -> tuple[list[str], str]:
        saved = self._expr_flat_lines
        lines: list[str] = []
        self._expr_flat_lines = lines
        try:
            value = build()
        finally:
            self._expr_flat_lines = saved
        return lines, value

    def _flat_lines_wrap(self, flat: list[str], final_lines: list[str], depth: int) -> list[str]:
        if not flat:
            return [("    " * depth) + line for line in final_lines]
        self.temp_id += 1
        mark = f"_slug_expr_root_{self.temp_id}"
        p = "    " * depth
        q = "    " * (depth + 1)
        return [p + "{", q + f"size_t {mark}=sv_temp_root_mark();"] + [q + line for line in flat] + [q + line for line in final_lines] + [q + f"sv_temp_root_pop({mark});", p + "}"]

    def _eval_seq(self, values: list[str] | tuple[str, ...], final: str) -> str:
        parts = ["sv_eval_begin()"]
        parts.extend(f"sv_eval_push({value})" for value in values)
        parts.append(final)
        return "(" + ", ".join(parts) + ")"

    def _eval_exprs(self, args: tuple[ast.Expr, ...]) -> list[str]:
        return ["sv_default()" if isinstance(a, ast.DefaultArg) else self._expr(a) for a in args]

    def _arg_array(self, args: tuple[ast.Expr, ...]) -> tuple[int, str]:
        vals = ["sv_default()" if isinstance(a, ast.DefaultArg) else self._expr(a) for a in args]
        arr = "NULL" if not vals else "(SlugValue[]){" + ", ".join(vals) + "}"
        return len(vals), arr

    def _call_raw(self, e: ast.Call) -> str:
        if e.name not in self.functions:
            raise CodegenError(f"{e.name!r} is not a user function")
        return self._eval_seq(self._eval_exprs(e.args), f"sv_eval_call_result({self._fn_cname(e.name)})")

    def _method_call_raw(self, e: ast.MethodCall) -> str:
        args = self._eval_exprs(e.args)
        if e.super_call:
            if self.current_class is None or self.current_self is None:
                raise CodegenError("super method call outside instance class context")
            parent = self.classes[self.current_class].parent
            if parent is None:
                raise CodegenError(f"class {self.current_class} has no parent")
            found = self._lookup_method_owner(parent, e.name, False)
            if found is None:
                raise CodegenError(f"unknown parent method {e.name}")
            owner, _ = found
            return self._eval_seq([f"sv_object_value({self.current_self})", *args], f"sv_eval_call_method({self._method_cname(owner, e.name, False)})")
        if e.class_name is not None:
            found = self._lookup_method_owner(e.class_name, e.name, True)
            if found is None:
                raise CodegenError(f"unknown static method {e.class_name}.{e.name}")
            owner, _ = found
            return self._eval_seq(args, f"sv_eval_call_result({self._method_cname(owner, e.name, True)})")
        if e.receiver is not None:
            return self._eval_seq([self._expr(e.receiver), *args], f"sv_eval_call_method({self._dispatch_cname(e.name)})")
        if self.current_class is None:
            raise CodegenError("current method call outside class")
        if e.static:
            found = self._lookup_method_owner(self.current_class, e.name, True)
            if found is None:
                raise CodegenError(f"unknown static method {self.current_class}.{e.name}")
            owner, _ = found
            return self._eval_seq(args, f"sv_eval_call_result({self._method_cname(owner, e.name, True)})")
        if self.current_self is None:
            raise CodegenError("instance method call from static context")
        return self._eval_seq([f"sv_object_value({self.current_self})", *args], f"sv_eval_call_method({self._dispatch_cname(e.name)})")

    def _result_call_raw(self, e: ast.Expr) -> str:
        if isinstance(e, ast.Call) and e.name in self.functions:
            return self._call_raw(e)
        if isinstance(e, ast.MethodCall):
            return self._method_call_raw(e)
        if isinstance(e, ast.CallableInvoke):
            return self._eval_seq([self._expr(e.callee), *self._eval_exprs(e.args)], "sv_eval_invoke()")
        raise CodegenError("expression is not a result-returning call")

    def _is_result_call(self, e: ast.Expr) -> bool:
        return (isinstance(e, ast.Call) and e.name in self.functions) or isinstance(e, (ast.MethodCall, ast.CallableInvoke))

    def _class_call_expr(self, e: ast.ClassCall) -> str:
        return self._eval_seq(self._eval_exprs(e.args), f"sv_eval_call_value({self._ctor_cname(e.name)})")

    def _member_get_expr(self, e: ast.MemberExpr) -> str:
        if e.class_name is not None:
            return self._static_field_var(e.class_name, e.name)
        if e.base is not None:
            return self._eval_seq([self._expr(e.base)], f"sv_eval_object_get({_c_string(e.name)})")
        if e.static:
            if self.current_class is None:
                raise CodegenError("..field outside class")
            return self._static_field_var(self.current_class, e.name)
        return f"sv_object_get({self._self_value()}, {_c_string(e.name)})"

    def _member_set_expr(self, target: ast.MemberExpr, value: str, *, define: bool, immutable: bool, initialization: bool = False) -> str:
        if target.class_name is not None:
            v = self._static_field_var(target.class_name, target.name)
            return f"({v} = {value})"
        if target.base is not None:
            return self._eval_seq([self._expr(target.base), value], f"sv_eval_object_set({_c_string(target.name)}, {'true' if define else 'false'}, {'true' if immutable else 'false'}, {'true' if initialization else 'false'})")
        if target.static:
            if self.current_class is None:
                raise CodegenError("..field assignment outside class")
            v = self._static_field_var(self.current_class, target.name)
            return f"({v} = {value})"
        return f"sv_object_set({self._self_value()}, {_c_string(target.name)}, {value}, {'true' if define else 'false'}, {'true' if immutable else 'false'}, {'true' if initialization else 'false'})"

    def generate(self)->str:
        lines=[_RUNTIME]
        if self.globals:
            lines.append("\n/* module bindings */")
            for cv in self.globals.values(): lines.append(f"static SlugCell *{cv};")
        if self.static_fields:
            lines.append("\n/* class static fields */")
            for cv in self.static_fields.values(): lines.append(f"static SlugValue {cv};")

        active_functions=[self.functions[n] for n in self.functions if n in self.reachable_functions]
        if active_functions or self.classes or self.lambda_nodes:
            lines.append("\n/* SLUG prototypes */")
            for fn in active_functions:
                lines.append(f"static SlugResult {self._fn_cname(fn.name)}(size_t argc, SlugValue *argv);")
            for lid in sorted(self.lambda_nodes):
                lines.append(f"static SlugResult {self._lambda_cname(lid)}(SlugClosure *closure, size_t argc, SlugValue *argv);")
            for cname, cls in self.classes.items():
                lines.append(f"static void {self._init_cname(cname)}(SlugObject *self, size_t argc, SlugValue *argv);")
                lines.append(f"static SlugValue {self._ctor_cname(cname)}(size_t argc, SlugValue *argv);")
                lines.append(f"static void {self._dtor_cname(cname)}(SlugObject *self);")
                for (static,name), fn in self.class_methods[cname].items():
                    if static:
                        lines.append(f"static SlugResult {self._method_cname(cname,name,True)}(size_t argc, SlugValue *argv);")
                    else:
                        lines.append(f"static SlugResult {self._method_cname(cname,name,False)}(SlugObject *self, size_t argc, SlugValue *argv);")
            method_names=sorted({name for methods in self.class_methods.values() for (static,name) in methods if not static})
            for name in method_names:
                lines.append(f"static SlugResult {self._dispatch_cname(name)}(SlugObject *self, size_t argc, SlugValue *argv);")
            lines.append("static void slug_destroy_object(SlugObject *self);")

        if active_functions:
            lines.append("\n/* SLUG function bodies */")
            for fn in active_functions: lines.extend(self._function_def(fn))

        if self.classes:
            lines.append("\n/* SLUG class bodies */")
            for cname in self.classes:
                lines.extend(self._class_init_def(cname))
                lines.extend(self._class_ctor_def(cname))
                for (static,name), fn in self.class_methods[cname].items():
                    lines.extend(self._method_def(cname, fn))
                lines.extend(self._dtor_def(cname))
            for name in sorted({n for methods in self.class_methods.values() for (st,n) in methods if not st}):
                lines.extend(self._dispatch_def(name))
            lines.extend(self._destroy_dispatch_def())

        lines += ["\nint main(int argc, char **argv){","    sv_argc=argc; sv_argv=argv;","    sv_runtime_init();"]
        if self.classes:
            lines.append("    sv_object_destructor = slug_destroy_object;")
        for cv in self.globals.values():
            lines.append(f"    {cv} = sv_cell_new();")
        for cv in self.static_fields.values():
            lines.append(f"    sv_root_slot(&{cv});")
        self._push_root_scope()
        # Static field definitions execute once, before ordinary module code.
        saved_class, saved_self, saved_static, saved_mode = self.current_class, self.current_self, self.current_static_method, self.current_mode
        for cname in self.classes:
            self.current_class=cname; self.current_self=None; self.current_static_method=True; self.current_mode="static_init"
            for (static,fname),(target,value,immutable) in self.field_decls[cname].items():
                if static:
                    lines.append(f"    {self.static_fields[(cname,fname)]} = {self._expr(value)};")
        self.current_class, self.current_self, self.current_static_method, self.current_mode = saved_class, saved_self, saved_static, saved_mode
        for s in self.program.statements:
            if isinstance(s, (ast.FunctionDecl, ast.ClassDecl)):
                continue
            lines.extend(self._stmt_gc(s,1))
        self._pop_scope();lines.append("    sv_gc_collect();");lines.append("    return sv_runtime_shutdown() ? 66 : 0;");lines.append("}")
        emitted:set[int]=set()
        while True:
            pending=[lid for lid in sorted(self.lambda_specs) if lid not in emitted]
            if not pending:break
            for lid in pending:
                lines.append("\n/* SLUG lambda body */")
                lines.extend(self._lambda_def(lid));emitted.add(lid)
        return "\n".join(lines)+"\n"

    def _emit_param_bindings(self, params: tuple[ast.Param,...], variadic: str|None, label: str, depth: int) -> list[str]:
        p="    "*depth;out=[];fixed=len(params)
        if variadic is None:
            out.append(p+f"if(argc>{fixed}) sv_fail(\"too many arguments for {label}\");")
        for i,param in enumerate(params):
            v=self._resolve(param.name); assert v is not None
            incoming=f"argv[{i}]"
            if param.type_code:
                incoming=self._contract_expr(param.type_code,incoming)
            out.append(p+f"if(argc>{i} && argv[{i}].tag!=SV_DEFAULT) {v}={incoming};")
            if param.default is not None:
                default=self._expr(param.default)
                if param.type_code:
                    default=self._contract_expr(param.type_code,default)
                out.append(p+f"else {v}={default};")
            else:
                out.append(p+f"else sv_fail(\"missing required argument {param.name} for {label}\");")
        if variadic:
            vv=self._resolve(variadic);assert vv is not None
            out.append(p+f"for(size_t _i={fixed};_i<argc;_i++) if(argv[_i].tag==SV_DEFAULT) sv_fail(\"xx is invalid in variadic tail\");")
            out.append(p+f"{vv}=sv_list_from_args(argc>{fixed}?argv+{fixed}:NULL, argc>{fixed}?argc-{fixed}:0);")
        return out

    def _function_def(self, fn: ast.FunctionDecl) -> list[str]:
        saved_scopes=self.scopes; saved_fn=self.current_function; saved_root=self.function_scope_frame; saved_loops=self.loop_scope_frames
        saved_class,saved_self,saved_static,saved_mode=self.current_class,self.current_self,self.current_static_method,self.current_mode
        self.scopes=[]; self.current_function=fn;self.current_class=None;self.current_self=None;self.current_static_method=False;self.current_mode="function";self.loop_scope_frames=[]
        forced=tuple(p.name for p in fn.params)+((fn.variadic,) if fn.variadic else ())
        out=[f"static SlugResult {self._fn_cname(fn.name)}(size_t argc, SlugValue *argv){{"]
        decls=self._push_scope(fn.body,forced,{p.name:p.type_code for p in fn.params});root=self._current_scope_frame();self.function_scope_frame=root;out.extend("    "+d for d in decls)
        out.extend(self._emit_param_bindings(fn.params,fn.variadic,fn.name,1))
        for child in fn.body: out.extend(self._stmt_gc(child,1))
        out.append(f"    sv_scope_leave(&{root});");out.append("    return sv_result0();");out.append("}")
        self._pop_scope();self.scopes=saved_scopes;self.current_function=saved_fn;self.function_scope_frame=saved_root;self.loop_scope_frames=saved_loops
        self.current_class,self.current_self,self.current_static_method,self.current_mode=saved_class,saved_self,saved_static,saved_mode
        return out

    def _is_static_field_decl_stmt(self, s: ast.Stmt) -> bool:
        if isinstance(s,ast.ExprStmt) and isinstance(s.expr,ast.SetMemberExpr):
            t=s.expr.target;return t.base is None and t.class_name is None and t.static
        if isinstance(s,ast.SetMemberStmt) and s.define:
            t=s.target;return t.base is None and t.class_name is None and t.static
        return False

    def _class_init_def(self, cname: str) -> list[str]:
        cls=self.classes[cname]
        body=tuple(s for s in cls.body if not isinstance(s,(ast.FunctionDecl,ast.DestructorDecl)) and not self._is_static_field_decl_stmt(s))
        saved_scopes=self.scopes;saved_fn=self.current_function;saved_root=self.function_scope_frame;saved_loops=self.loop_scope_frames
        saved_class,saved_self,saved_static,saved_mode=self.current_class,self.current_self,self.current_static_method,self.current_mode
        self.scopes=[];self.current_function=None;self.current_class=cname;self.current_self="self";self.current_static_method=False;self.current_mode="constructor";self.loop_scope_frames=[]
        forced=tuple(p.name for p in cls.params)
        out=[f"static void {self._init_cname(cname)}(SlugObject *self, size_t argc, SlugValue *argv){{"]
        decls=self._push_scope(body,forced,{p.name:p.type_code for p in cls.params});root=self._current_scope_frame();self.function_scope_frame=root;out.extend("    "+d for d in decls)
        out.append("    (void)sv_cell_from(sv_object_value(self));")
        out.extend(self._emit_param_bindings(cls.params,None,cname,1))
        explicit_super=any(isinstance(s,ast.SuperInitStmt) for s in body)
        if cls.parent and not explicit_super:
            out.append(f"    {self._init_cname(cls.parent)}(self, 0, NULL);")
        for child in body:out.extend(self._stmt_gc(child,1))
        out.append(f"    sv_scope_leave(&{root});");out.append("    return;");out.append("}")
        self._pop_scope();self.scopes=saved_scopes;self.current_function=saved_fn;self.function_scope_frame=saved_root;self.loop_scope_frames=saved_loops
        self.current_class,self.current_self,self.current_static_method,self.current_mode=saved_class,saved_self,saved_static,saved_mode
        return out

    def _class_ctor_def(self,cname:str)->list[str]:
        cid=self.class_ids[cname]
        return [f"static SlugValue {self._ctor_cname(cname)}(size_t argc, SlugValue *argv){{",f"    SlugObject *self=sv_object_new({cid}, {_c_string(cname)});",f"    {self._init_cname(cname)}(self,argc,argv);","    return sv_object_value(self);","}"]

    def _method_def(self,cname:str,fn:ast.FunctionDecl)->list[str]:
        saved_scopes=self.scopes;saved_fn=self.current_function;saved_root=self.function_scope_frame;saved_loops=self.loop_scope_frames
        saved_class,saved_self,saved_static,saved_mode=self.current_class,self.current_self,self.current_static_method,self.current_mode
        self.scopes=[];self.current_function=fn;self.current_class=cname;self.current_static_method=fn.static;self.current_self=None if fn.static else "self";self.current_mode="method";self.loop_scope_frames=[]
        forced=tuple(p.name for p in fn.params)+((fn.variadic,) if fn.variadic else ())
        sig=(f"static SlugResult {self._method_cname(cname,fn.name,True)}(size_t argc, SlugValue *argv){{" if fn.static else f"static SlugResult {self._method_cname(cname,fn.name,False)}(SlugObject *self, size_t argc, SlugValue *argv){{")
        out=[sig];decls=self._push_scope(fn.body,forced,{p.name:p.type_code for p in fn.params});root=self._current_scope_frame();self.function_scope_frame=root;out.extend("    "+d for d in decls)
        if not fn.static:out.append("    (void)sv_cell_from(sv_object_value(self));")
        out.extend(self._emit_param_bindings(fn.params,fn.variadic,f"{cname}.{fn.name}",1))
        for child in fn.body:out.extend(self._stmt_gc(child,1))
        out.append(f"    sv_scope_leave(&{root});");out.append("    return sv_result0();");out.append("}")
        self._pop_scope();self.scopes=saved_scopes;self.current_function=saved_fn;self.function_scope_frame=saved_root;self.loop_scope_frames=saved_loops
        self.current_class,self.current_self,self.current_static_method,self.current_mode=saved_class,saved_self,saved_static,saved_mode
        return out

    def _dtor_def(self,cname:str)->list[str]:
        saved_scopes=self.scopes;saved_fn=self.current_function;saved_root=self.function_scope_frame;saved_loops=self.loop_scope_frames
        saved_class,saved_self,saved_static,saved_mode=self.current_class,self.current_self,self.current_static_method,self.current_mode
        self.scopes=[];self.current_function=None;self.current_class=cname;self.current_self="self";self.current_static_method=False;self.current_mode="destructor";self.loop_scope_frames=[]
        dtor=self.class_destructors[cname];body=dtor.body if dtor else ()
        out=[f"static void {self._dtor_cname(cname)}(SlugObject *self){{"]
        decls=self._push_scope(body);root=self._current_scope_frame();self.function_scope_frame=root;out.extend("    "+d for d in decls)
        out.append("    (void)sv_cell_from(sv_object_value(self));")
        for child in body:out.extend(self._stmt_gc(child,1))
        if self.classes[cname].parent:
            out.append(f"    {self._dtor_cname(self.classes[cname].parent)}(self);")
        out.append(f"    sv_scope_leave(&{root});");out.append("}")
        self._pop_scope();self.scopes=saved_scopes;self.current_function=saved_fn;self.function_scope_frame=saved_root;self.loop_scope_frames=saved_loops
        self.current_class,self.current_self,self.current_static_method,self.current_mode=saved_class,saved_self,saved_static,saved_mode
        return out

    def _dispatch_def(self,name:str)->list[str]:
        out=[f"static SlugResult {self._dispatch_cname(name)}(SlugObject *self, size_t argc, SlugValue *argv){{","    if(!self)sv_fail(\"null object receiver\");","    switch(self->class_id){"]
        for cname,cid in self.class_ids.items():
            found=self._lookup_method_owner(cname,name,False)
            if found is not None:
                owner,_=found;out.append(f"        case {cid}: return {self._method_cname(owner,name,False)}(self,argc,argv);")
        out += ["        default: sv_fail(\"object does not implement requested method\");","    }","    return sv_result0();","}"]
        return out

    def _destroy_dispatch_def(self)->list[str]:
        out=["static void slug_destroy_object(SlugObject *self){","    if(!self)return;","    switch(self->class_id){"]
        for cname,cid in self.class_ids.items():out.append(f"        case {cid}: {self._dtor_cname(cname)}(self); break;")
        out += ["        default: break;","    }","}"]
        return out

    def _block(self,body:tuple[ast.Stmt,...],depth:int,forced:tuple[str,...]=(),*,loop_body:bool=False)->list[str]:
        p="    "*depth;out=[];out.extend(p+d for d in self._push_scope(body,forced));frame=self._current_scope_frame()
        if loop_body:self.loop_scope_frames.append(frame)
        try:
            for child in body:out.extend(self._stmt_gc(child,depth))
        finally:
            if loop_body:self.loop_scope_frames.pop()
        out.append(p+f"sv_scope_leave(&{frame});")
        out.append(p+"sv_gc_safepoint();")
        self._pop_scope();return out

    def _assignment_targets(self, names: tuple[str,...], current: bool) -> list[str]:
        out=[]
        for name in names:
            if current:
                v=self._define_current(name)
            else:
                v=self._resolve(name)
                if v is None:raise CodegenError(f"undefined binding {name!r}; use := to define it")
            out.append(v)
        return out

    def _assign_lines(self, names: tuple[str,...], value: ast.Expr, depth:int, current: bool) -> list[str]:
        targets=self._assignment_targets(names,current)
        contracts=[self._binding_contract(n,current) for n in names]
        if self._is_result_call(value):
            flat, raw = self._flat_expr_capture(lambda: self._result_call_raw(value))
            self.temp_id+=1; r=f"_slug_res_{self.temp_id}"
            body=[f"SlugResult {r} = {raw};",f"sv_result_require_arity({r}, {len(targets)});"]
            staged=[]
            for i,c in enumerate(contracts):
                self.temp_id+=1; tmp=f"_slug_assign_{self.temp_id}"; picked=f"sv_result_pick({r}, {i})"
                rhs=self._contract_expr(c,picked) if c else picked
                body.append(f"SlugValue {tmp} = {rhs};");staged.append(tmp)
            for v,tmp in zip(targets,staged):body.append(f"{v} = {tmp};")
            body.append(f"sv_result_dispose({r});")
            return self._flat_lines_wrap(flat,body,depth)
        flat, rhs = self._flat_expr_capture(lambda: self._expr(value))
        if len(targets)==1:
            rhs=self._contract_expr(contracts[0],rhs) if contracts[0] else rhs
            return self._flat_lines_wrap(flat,[f"{targets[0]} = {rhs};"],depth)
        self.temp_id+=1;src=f"_slug_src_{self.temp_id}";body=[f"SlugValue {src} = {rhs};"]
        staged=[]
        for c in contracts:
            self.temp_id+=1;tmp=f"_slug_assign_{self.temp_id}";val=self._contract_expr(c,src) if c else src
            body.append(f"SlugValue {tmp} = {val};");staged.append(tmp)
        for v,tmp in zip(targets,staged):body.append(f"{v} = {tmp};")
        return self._flat_lines_wrap(flat,body,depth)

    def _finally_lines(self, ctx: dict[str, object], depth: int, pending: str | None = None) -> list[str]:
        body=ctx.get("finally")
        if not body:
            return []
        saved=self.try_stack
        try:
            if ctx in saved:
                idx=saved.index(ctx); self.try_stack=saved[:idx]
            else:
                self.try_stack=saved
            p="    "*depth
            if pending is None:
                return [p+"{"]+self._block(body,depth+1)+[p+"}"]
            self.temp_id+=1;uid=self.temp_id
            ff=f"_slug_finally_exc_{uid}";fc=f"_slug_finally_code_{uid}";fe=f"_slug_finally_err_{uid}";fr=f"_slug_finally_root_{uid}";sup=f"_slug_finally_sup_{uid}"
            out=[p+"{",p+f"    SlugExcFrame {ff};",p+f"    sv_exc_push(&{ff});",p+f"    int {fc}=setjmp(SV_EXC_ENV(&{ff}));",p+f"    if({fc}==0) {{"]
            synthetic={"frame":ff,"finally":None,"loop_depth":self.cg_loop_depth}
            self.try_stack.append(synthetic)
            try: out.extend(self._block(body,depth+2))
            finally: self.try_stack.pop()
            out.append(p+f"        sv_exc_pop(&{ff});")
            out.append(p+"    } else {")
            out.append(p+f"        SlugValue {fe}=sv_exc_error(&{ff});")
            out.append(p+f"        size_t {fr}=sv_temp_root_push({fe});")
            out.append(p+f"        sv_exc_pop(&{ff});")
            out.append(p+f"        SlugValue {sup}=sv_error_supersede({fe},{pending});")
            out.append(p+f"        sv_temp_root_pop({fr});")
            out.append(p+f"        sv_raise({sup});")
            out += [p+"    }",p+"}"]
            return out
        finally:
            self.try_stack=saved

    def _unwind_for_control(self, kind: str, depth: int) -> list[str]:
        if kind in {"break","continue"}:
            selected=[c for c in self.try_stack if int(c.get("loop_depth",-1))>=self.cg_loop_depth]
        else:
            selected=list(self.try_stack)
        out: list[str]=[]
        p="    "*depth
        for ctx in reversed(selected):
            frame=ctx.get("frame")
            if frame:
                out.append(p+f"sv_scope_unwind_to(sv_exc_scope_base(&{frame}));")
                out.append(p+f"sv_exc_pop(&{frame});")
            out.extend(self._finally_lines(ctx,depth))
        if kind in {"break","continue"}:
            if not self.loop_scope_frames:raise CodegenError(f"{kind} outside runtime loop scope")
            out.append(p+f"sv_scope_unwind_through(&{self.loop_scope_frames[-1]});")
        elif kind=="return":
            if self.function_scope_frame is None:raise CodegenError("return has no runtime function scope")
            out.append(p+f"sv_scope_unwind_through(&{self.function_scope_frame});")
        return out

    def _try_stmt(self, s: ast.TryStmt, depth: int) -> list[str]:
        p="    "*depth
        self.temp_id+=1;uid=self.temp_id
        frame=f"_slug_exc_{uid}";code=f"_slug_exc_code_{uid}";err=f"_slug_err_{uid}";eroot=f"_slug_err_root_{uid}"
        out=[p+"{",p+f"    SlugExcFrame {frame};",p+f"    sv_exc_push(&{frame});",p+f"    int {code}=setjmp(SV_EXC_ENV(&{frame}));",p+f"    if({code}==0) {{"]
        ctx={"frame":frame,"finally":s.finally_body,"loop_depth":self.cg_loop_depth}
        self.try_stack.append(ctx)
        out.extend(self._block(s.body,depth+2))
        self.try_stack.pop()
        out.append(p+f"        sv_exc_pop(&{frame});")
        out.extend(self._finally_lines(ctx,depth+2))
        out.append(p+"    } else {")
        out.append(p+f"        SlugValue {err}=sv_exc_error(&{frame});")
        out.append(p+f"        size_t {eroot}=sv_temp_root_push({err});")
        out.append(p+f"        sv_exc_pop(&{frame});")
        if s.catch_body is not None:
            forced=(s.catch_name,) if s.catch_name else ()
            decls=self._push_scope(s.catch_body,forced);catch_scope=self._current_scope_frame()
            out.extend("    "*(depth+2)+d for d in decls)
            if s.catch_name:
                v=self._resolve(s.catch_name);out.append("    "*(depth+2)+f"{v}={err};")
            self.temp_id+=1;cid=self.temp_id
            cf=f"_slug_catch_exc_{cid}";cc=f"_slug_catch_code_{cid}";ce=f"_slug_catch_err_{cid}";ceroot=f"_slug_catch_root_{cid}"
            out += [p+f"        SlugExcFrame {cf};",p+f"        sv_exc_push(&{cf});",p+f"        int {cc}=setjmp(SV_EXC_ENV(&{cf}));",p+f"        if({cc}==0) {{"]
            cctx={"frame":cf,"finally":s.finally_body,"loop_depth":self.cg_loop_depth}
            self.try_stack.append(cctx);self.catch_error_stack.append(err)
            try:
                for child in s.catch_body:out.extend(self._stmt_gc(child,depth+3))
            finally:
                self.catch_error_stack.pop();self.try_stack.pop()
            out.append(p+f"            sv_exc_pop(&{cf});")
            out.extend(self._finally_lines(cctx,depth+3))
            out.append(p+f"            sv_scope_leave(&{catch_scope});")
            out.append(p+f"            sv_temp_root_pop({eroot});")
            out.append(p+"        } else {")
            out.append(p+f"            SlugValue {ce}=sv_exc_error(&{cf});")
            out.append(p+f"            size_t {ceroot}=sv_temp_root_push({ce});")
            out.append(p+f"            sv_exc_pop(&{cf});")
            out.extend(self._finally_lines(cctx,depth+3,ce))
            out.append(p+f"            sv_scope_leave(&{catch_scope});")
            out.append(p+f"            sv_temp_root_pop({ceroot});")
            out.append(p+f"            sv_temp_root_pop({eroot});")
            out.append(p+f"            sv_raise({ce});")
            out.append(p+"        }")
            self._pop_scope()
        else:
            out.extend(self._finally_lines(ctx,depth+2,err))
            out.append(p+f"        sv_temp_root_pop({eroot});")
            out.append(p+f"        sv_raise({err});")
        out += [p+"    }",p+"}"]
        return out

    def _stmt(self,s:ast.Stmt,depth:int)->list[str]:
        p="    "*depth
        if isinstance(s,ast.CommentStmt):return []
        if isinstance(s,ast.ImportStmt):return []
        if isinstance(s,ast.NamespaceStmt):return []
        if isinstance(s,ast.InterfaceDecl):return []
        if isinstance(s,ast.RaiseStmt):
            if s.value is None:
                if not self.catch_error_stack: raise CodegenError("bare er outside catch")
                return [p+f"sv_raise({self.catch_error_stack[-1]});"]
            flat, value = self._flat_expr_capture(lambda: self._expr(s.value))
            return self._flat_lines_wrap(flat,[f"sv_raise({value});"],depth)
        if isinstance(s,ast.TryStmt):return self._try_stmt(s,depth)
        if isinstance(s,ast.ExprStmt):
            if isinstance(s.expr,ast.AssignExpr) and len(s.expr.targets)>1:
                return self._assign_lines(s.expr.targets,s.expr.value,depth,True)
            if self._is_result_call(s.expr):
                flat, raw = self._flat_expr_capture(lambda: self._result_call_raw(s.expr))
                return self._flat_lines_wrap(flat,["sv_result_discard("+raw+");"],depth)
            flat, value = self._flat_expr_capture(lambda: self._expr(s.expr))
            return self._flat_lines_wrap(flat,[value+";"],depth)
        if isinstance(s,ast.AssignStmt): return self._assign_lines(s.targets,s.value,depth,False)
        if isinstance(s,ast.SetIndexStmt):
            flat, code = self._flat_expr_capture(lambda: self._eval_seq([self._expr(s.target.base),self._expr(s.target.index),self._expr(s.value)],"sv_eval_set_index(false)"))
            return self._flat_lines_wrap(flat,[code+";"],depth)
        if isinstance(s,ast.SetMemberStmt):
            init = self.current_mode in {"constructor","static_init"}
            flat, code = self._flat_expr_capture(lambda: self._member_set_expr(s.target,self._expr(s.value),define=s.define,immutable=s.immutable,initialization=init))
            return self._flat_lines_wrap(flat,[code+";"],depth)
        if isinstance(s,ast.SuperInitStmt):
            if self.current_class is None or self.current_self is None:
                raise CodegenError("^^[...] outside constructor")
            parent=self.classes[self.current_class].parent
            if parent is None:raise CodegenError(f"class {self.current_class} has no parent")
            call=self._eval_seq([f"sv_object_value({self.current_self})", *self._eval_exprs(s.args)], f"sv_eval_call_init({self._init_cname(parent)})")
            return [p+call+";"]
        if isinstance(s,ast.DestructorDecl):return []
        if isinstance(s,ast.MutateStmt):
            fn='sv_inc' if s.op=='++' else 'sv_dec'
            if isinstance(s.target,(ast.Var,ast.ExtendedName)):
                v=self._resolve(s.target.name)
                if v is None:raise CodegenError(f"undefined binding {s.target.name!r}")
                code=f"{fn}({v})"
                contract=self._binding_contract(s.target.name,False)
                if contract:code=self._contract_expr(contract,code)
                return [p+f"{v} = {code};"]
            if isinstance(s.target,ast.MemberExpr):
                if s.target.base is not None:
                    # Evaluate a computed receiver exactly once.  Re-reading the receiver
                    # for the write would duplicate source-visible side effects.
                    return [p+self._eval_seq([self._expr(s.target.base)],f"sv_eval_object_mutate({_c_string(s.target.name)}, {'true' if s.op=='++' else 'false'})")+";"]
                cur=self._member_get_expr(s.target)
                return [p+self._member_set_expr(s.target,f"{fn}({cur})",define=False,immutable=False,initialization=False)+";"]
            raise CodegenError("unsupported mutation target")
        if isinstance(s,ast.IfStmt):
            out=[p+f"if ({self._bool(s.condition)}) {{"]+self._block(s.body,depth+1);out.append(p+"}")
            for cond,body in s.elifs:
                out[-1]+=f" else if ({self._bool(cond)}) {{";out+=self._block(body,depth+1);out.append(p+"}")
            if s.else_body is not None:out[-1]+=" else {";out+=self._block(s.else_body,depth+1);out.append(p+"}")
            return out
        if isinstance(s,ast.WhileStmt):
            self.cg_loop_depth+=1
            try: body=self._block(s.body,depth+1,loop_body=True)
            finally:self.cg_loop_depth-=1
            return [p+f"while ({self._bool(s.condition)}) {{"]+body+[p+"}"]
        if isinstance(s,ast.ForStmt):
            if s.kind=="repeat":
                self.temp_id+=1;n=f"_slug_n_{self.temp_id}";i=f"_slug_i_{self.temp_id}";count=self._expr(s.start)
                self.cg_loop_depth+=1
                try: body=self._block(s.body,depth+2,loop_body=True)
                finally:self.cg_loop_depth-=1
                return [p+"{",p+f"    uint64_t {n}=sv_repeat_count({count});",p+f"    for(uint64_t {i}=0;{i}<{n};++{i}) {{"]+body+[p+"    }",p+"}"]
            if s.kind=="range":
                self.temp_id+=1;uid=self.temp_id;a=f"_slug_a_{uid}";b=f"_slug_b_{uid}";it=f"_slug_it_{uid}";au=f"_slug_allow_u_{uid}";begin=self._expr(s.start);stop=self._expr(s.stop)
                # Use the C `for` increment clause for the range advance.  A SLUG
                # `continue` lowers to C `continue`, which must still advance the
                # numeric iterator; a bottom-of-body increment would be skipped and
                # could turn a perfectly legal loop into an infinite loop.
                out=[p+"{",p+f"    SlugValue {a}={begin};",p+f"    SlugValue {b}={stop};",p+f"    sv_require_range_bound({a}); sv_require_range_bound({b});",p+f"    bool {au}=({a}.tag==SV_UINT||{b}.tag==SV_UINT);",p+f"    SlugValue {it}={a};",p+f"    for(;sv_numeric_compare({it},{b})<0;{it}=sv_range_next({it},{au})) {{"]
                self.cg_loop_depth+=1
                try:
                    decls=self._push_scope(s.body,(s.var,));frame=self._current_scope_frame();self.loop_scope_frames.append(frame);out.extend("    "*(depth+2)+d for d in decls);v=self._resolve(s.var);out.append("    "*(depth+2)+f"{v}={it};")
                    try:
                        for child in s.body:out.extend(self._stmt_gc(child,depth+2))
                    finally:self.loop_scope_frames.pop()
                    out.append("    "*(depth+2)+f"sv_scope_leave(&{frame});");out.append("    "*(depth+2)+"sv_gc_safepoint();")
                    self._pop_scope()
                finally:self.cg_loop_depth-=1
                out += [p+"    }",p+"}"];return out
            if s.kind in {"foreach","slice","slice_step"}:
                self.temp_id+=1;uid=self.temp_id;seq=f"_slug_seq_{uid}";n=f"_slug_n_{uid}";it=f"_slug_it_{uid}"
                if s.kind=="foreach": seqexpr=self._expr(s.source)
                else:
                    start=self._expr(s.start);stop=self._expr(s.stop);step=self._expr(s.step) if s.step is not None else "sv_null()"
                    seqexpr=self._eval_seq([self._expr(s.source),start,stop,step],"sv_eval_slice()")
                root=f"_slug_seq_root_{uid}"
                out=[p+"{",p+f"    SlugValue {seq}=sv_iteration_snapshot({seqexpr});",p+f"    size_t {root}=sv_temp_root_push({seq});",p+f"    size_t {n}=sv_len_size({seq});",p+f"    for(size_t {it}=0;{it}<{n};++{it}) {{"]
                self.cg_loop_depth+=1
                try:
                    decls=self._push_scope(s.body,(s.var,));frame=self._current_scope_frame();self.loop_scope_frames.append(frame);out.extend("    "*(depth+2)+d for d in decls);v=self._resolve(s.var);out.append("    "*(depth+2)+f"{v}=sv_iter_at({seq},{it});")
                    try:
                        for child in s.body:out.extend(self._stmt_gc(child,depth+2))
                    finally:self.loop_scope_frames.pop()
                    out.append("    "*(depth+2)+f"sv_scope_leave(&{frame});");out.append("    "*(depth+2)+"sv_gc_safepoint();")
                    self._pop_scope()
                finally:self.cg_loop_depth-=1
                out += [p+"    }",p+f"    sv_temp_root_pop({root});",p+"    sv_gc_safepoint();",p+"}"];return out
            raise CodegenError(f"unknown fl kind {s.kind}")
        if isinstance(s,ast.BreakStmt):return self._unwind_for_control("break",depth)+[p+"break;"]
        if isinstance(s,ast.ContinueStmt):return self._unwind_for_control("continue",depth)+[p+"continue;"]
        if isinstance(s,ast.FunctionDecl):return []
        if isinstance(s,ast.ClassDecl):return []
        if isinstance(s,ast.ReturnStmt):
            if self.current_mode in {"constructor","destructor"}:
                flat, vals = self._flat_expr_capture(lambda: [self._expr(v) for v in s.values])
                body=[f"(void)({v});" for v in vals]
                wrapped=self._flat_lines_wrap(flat,body,depth)
                wrapped.extend(self._unwind_for_control("return",depth));wrapped.append(p+"return;")
                return wrapped
            if self.current_function is None: raise CodegenError("top-level return is not supported")
            def lower_values():
                vals=[]
                for i,v in enumerate(s.values):
                    code=self._expr(v)
                    if self.current_function.return_types is not None:
                        code=self._contract_expr(self.current_function.return_types[i],code)
                    vals.append(code)
                return vals
            flat, vals = self._flat_expr_capture(lower_values)
            self.temp_id+=1;r=f"_slug_return_{self.temp_id}"
            self.temp_id+=1;rr=f"_slug_return_root_{self.temp_id}"
            if not flat:
                out=[p+(f"SlugResult {r}=sv_result0();" if not vals else f"SlugResult {r}="+self._eval_seq(vals,"sv_eval_result_values()")+";")]
                out.append(p+f"size_t {rr}=sv_result_root({r});");out.append(p+f"(void){rr};")
                out.extend(self._unwind_for_control("return",depth));out.append(p+f"return {r};");return out
            self.temp_id+=1;mark=f"_slug_expr_root_{self.temp_id}";q="    "*(depth+1)
            out=[p+"{",q+f"size_t {mark}=sv_temp_root_mark();"]+[q+line for line in flat]
            out.append(q+(f"SlugResult {r}=sv_result0();" if not vals else f"SlugResult {r}="+self._eval_seq(vals,"sv_eval_result_values()")+";"))
            out.append(q+f"size_t {rr}=sv_result_root({r});");out.append(q+f"(void){rr};");out.append(q+f"sv_temp_root_pop({mark});")
            out.extend(self._unwind_for_control("return",depth+1));out.append(q+f"return {r};");out.append(p+"}");return out
        raise CodegenError(f"bootstrap C backend does not lower {type(s).__name__} yet")

    def _optimizer_substitution_safe(self, e: ast.Expr) -> bool:
        """Whether replacing *e* by a proven scalar constant preserves evaluation.

        MIR may know the value of an expression whose subtree still performs a
        source-visible action (most importantly an embedded assignment).  Value
        knowledge is useful to later SSA users, but the C backend must not erase the
        evaluation that produced it.  Keep this intentionally conservative until MIR
        carries first-class effect summaries.
        """
        if isinstance(e, (ast.Literal, ast.Var, ast.ExtendedName)):
            return True
        if isinstance(e, ast.Cast):
            return self._optimizer_substitution_safe(e.value)
        if isinstance(e, ast.DynamicCast):
            return False
        if isinstance(e, (ast.Unary, ast.BoolExpr, ast.LogicNot)):
            return self._optimizer_substitution_safe(e.value)
        if isinstance(e, (ast.Binary, ast.Compare, ast.LogicBinary)):
            return self._optimizer_substitution_safe(e.left) and self._optimizer_substitution_safe(e.right)
        if isinstance(e, ast.Call) and id(e) in self.optimizer_elidable_sources:
            return all(isinstance(a, ast.DefaultArg) or self._optimizer_substitution_safe(a) for a in e.args)
        # AssignExpr, other calls/invokes, constructors, mutation, allocation, indexing,
        # member access, lambdas, and dynamic forms all remain on the runtime path.
        return False

    def _optimized_const_c(self, e: ast.Expr) -> str | None:
        if not self._optimizer_substitution_safe(e):
            return None
        c = self.optimizer_constants.get(id(e))
        if c is None:
            return None
        if c.kind == "bool": return "sv_bool(true)" if c.value else "sv_bool(false)"
        if c.kind == "int":
            return f"sv_int({int(c.value)})"
        if c.kind == "uint":
            return f"sv_uint(UINT64_C({int(c.value)}))"
        if c.kind == "float": return f"sv_float({float(c.value)!r})"
        if c.kind == "string": return _c_slug_string(str(c.value))
        if c.kind == "null": return "sv_null()"
        return None

    def _optimized_truth(self, e: ast.Expr) -> bool | None:
        if not self._optimizer_substitution_safe(e):
            return None
        c = self.optimizer_constants.get(id(e))
        if c is None: return None
        if c.kind == "bool": return bool(c.value)
        if c.kind in {"int", "uint", "float"}: return c.value != 0
        if c.kind == "string": return len(str(c.value)) != 0
        if c.kind == "null": return False
        return None

    def _bool(self,e:ast.Expr)->str:
        known = self._optimized_truth(e)
        if known is not None:
            return "true" if known else "false"
        if isinstance(e,ast.BoolExpr):return self._bool(e.value)
        if isinstance(e,ast.LogicNot):return f"(!({self._bool(e.value)}))"
        if isinstance(e,ast.LogicBinary):
            # A flat-expression capture cannot hoist the RHS of && / ||: doing so
            # would destroy SLUG short-circuit semantics. Lower the branch
            # structurally when flattening is active, while keeping ordinary C
            # short-circuit operators in non-flat contexts.
            if self._expr_flat_lines is None:
                return f"(({self._bool(e.left)}) {'&&' if e.op=='and' else '||'} ({self._bool(e.right)}))"
            left = self._bool(e.left)
            self.temp_id += 1
            tmp = f"_slug_bool_{self.temp_id}"
            self._expr_flat_lines.append(f"bool {tmp} = ({left});")
            rhs_lines, rhs = self._flat_expr_capture(lambda: self._bool(e.right))
            guard = tmp if e.op == 'and' else f"!({tmp})"
            self._expr_flat_lines.append(f"if({guard}){{")
            self._expr_flat_lines.extend("    " + line for line in rhs_lines)
            self._expr_flat_lines.append(f"    {tmp} = ({rhs});")
            self._expr_flat_lines.append("}")
            return tmp
        if isinstance(e,ast.Compare):
            a,b=self._expr(e.left),self._expr(e.right)
            if e.op in {"==","!=","===","!=="}:
                fn="sv_equal" if e.op in {"==","!="} else "sv_identical"
                q=self._eval_seq([a,b],f"sv_eval_bool_binary({fn})")
                return f"(!({q}))" if e.op in {"!=","!=="} else q
            cmp=self._eval_seq([a,b],"sv_eval_compare(sv_compare)")
            return {"<":f"({cmp}<0)",">":f"({cmp}>0)","<=":f"({cmp}<=0)",">=":f"({cmp}>=0)"}[e.op]
        return f"sv_truthy({self._expr(e)})"

    def _expr(self,e:ast.Expr)->str:
        optimized = self._optimized_const_c(e)
        if optimized is not None:
            return optimized
        if isinstance(e,ast.Literal):
            if e.kind=="int":
                n=int(e.value)
                return f"sv_int({n})" if n<=0x7FFFFFFFFFFFFFFF else f"sv_uint(UINT64_C({n}))"
            if e.kind=="float":return f"sv_float({float(e.value)!r})"
            if e.kind=="string":return _c_slug_string(e.value)
            if e.kind=="null":return "sv_null()"
        if isinstance(e,ast.FormattedString):
            vals=[]
            for part in e.parts:
                if isinstance(part,str): vals.append(_c_slug_string(part))
                else: vals.append(self._cast_expr("s",self._expr(part)))
            return self._materialize_expr(self._eval_seq(vals,"sv_eval_format_string()"))
        if isinstance(e,ast.DefaultArg): return "sv_default()"
        if isinstance(e,(ast.Var,ast.ExtendedName)):
            v=self._resolve(e.name)
            if v is None:raise CodegenError(f"undefined binding {e.name!r}")
            return v
        if isinstance(e,(ast.BoolExpr,ast.Compare,ast.LogicNot,ast.LogicBinary)):return f"sv_bool({self._bool(e)})"
        if isinstance(e,ast.Unary) and e.op=="-":return self._materialize_expr(f"sv_neg({self._expr(e.value)})")
        if isinstance(e,ast.Binary):
            fn={"+":"sv_add","-":"sv_sub","*":"sv_mul","/":"sv_div","//":"sv_idiv","%":"sv_mod","^":"sv_pow"}.get(e.op)
            if fn:return self._materialize_expr(self._eval_seq([self._expr(e.left),self._expr(e.right)],f"sv_eval_binary({fn})"))
        if isinstance(e,ast.Cast): return self._materialize_expr(self._cast_expr(e.type_code,self._expr(e.value)))
        if isinstance(e,ast.DynamicCast): return self._materialize_expr(self._eval_seq([self._expr(e.type_expr),self._expr(e.value)],"sv_eval_binary(sv_cast_dynamic)"))
        if isinstance(e,ast.AssignExpr):
            if len(e.targets)!=1:raise CodegenError("nested multiple assignment cannot be consumed as one value")
            rhs=self._expr(e.value);v=self._define_current(e.targets[0]);contract=self._binding_contract(e.targets[0],True)
            if contract:rhs=self._contract_expr(contract,rhs)
            return f"({v} = {rhs})"
        if isinstance(e,ast.LambdaExpr):return self._materialize_expr(self._lambda_expr(e))
        if isinstance(e,ast.ListLiteral):
            if not e.items:return self._materialize_expr(f"sv_list_empty({'true' if e.frozen else 'false'})")
            return self._materialize_expr(self._eval_seq([self._expr(x) for x in e.items], f"sv_eval_list_literal({'true' if e.frozen else 'false'})"))
        if isinstance(e,ast.MapLiteral):
            if not e.entries:return self._materialize_expr(f"sv_map_empty({'true' if e.frozen else 'false'})")
            flat=[]
            for k,v in e.entries:flat.extend((self._expr(k),self._expr(v)))
            return self._materialize_expr(self._eval_seq(flat, f"sv_eval_map_literal({'true' if e.frozen else 'false'})"))
        if isinstance(e,ast.IndexExpr):return self._materialize_expr(self._eval_seq([self._expr(e.base),self._expr(e.index)],"sv_eval_binary(sv_index)"))
        if isinstance(e,ast.SliceExpr):
            a=self._expr(e.start) if e.start is not None else "sv_null()";b=self._expr(e.stop) if e.stop is not None else "sv_null()";c=self._expr(e.step) if e.step is not None else "sv_null()"
            return self._materialize_expr(self._eval_seq([self._expr(e.base),a,b,c],"sv_eval_slice()"))
        if isinstance(e,ast.SetIndexExpr):return self._materialize_expr(self._eval_seq([self._expr(e.target.base),self._expr(e.target.index),self._expr(e.value)],"sv_eval_set_index(true)"))
        if isinstance(e,ast.MemberExpr):return self._materialize_expr(self._member_get_expr(e)) if e.base is not None else self._member_get_expr(e)
        if isinstance(e,ast.SetMemberExpr):
            init=self.current_mode in {"constructor","static_init"}
            return self._materialize_expr(self._member_set_expr(e.target,self._expr(e.value),define=True,immutable=e.immutable,initialization=init))
        if isinstance(e,ast.CallableInvoke):return self._materialize_expr(f"sv_result_first({self._result_call_raw(e)})")
        if isinstance(e,ast.MethodCall):return self._materialize_expr(f"sv_result_first({self._method_call_raw(e)})")
        if isinstance(e,ast.ClassCall):return self._materialize_expr(self._class_call_expr(e))
        if isinstance(e,ast.Call):
            if e.name in self.functions:return self._materialize_expr(f"sv_result_first({self._call_raw(e)})")
            spec = builtin(e.name)
            if spec is not None:
                return self._materialize_expr(self._eval_seq(self._eval_exprs(e.args), f"sv_eval_call_value({spec.c_name})"))
            raise CodegenError(f"bootstrap C backend does not lower callable {e.name!r} yet")
        raise CodegenError(f"bootstrap C backend does not lower expression {type(e).__name__} yet")


def generate_c(program: ast.Program)->str:
    ir=lower_ir(program)
    optimized=optimize_mir(lower_mir(ir))
    return CGenerator(program,ir,optimized).generate()
