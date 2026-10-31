/* server.h: the read-only web server (DESIGN §7, §9.2): map tiles and dataset info for one or more
 * .gpt files over HTTP/1.1 (GET and HEAD). One thread per connection, at most SERVER_MAX_CONNECTIONS at
 * once, one request per connection, every request line, header and number checked before use. */
#ifndef SERVER_H
#define SERVER_H

#include <stddef.h>
#include <stdint.h>

#include "tilefile.h"

#define SERVER_MAX_DATASETS 32
#define SERVER_MAX_ID 32
#define SERVER_MAX_CONNECTIONS 64
#define SERVER_MAX_REQUEST 8192 /* request line + headers, bytes */
#define SERVER_TIMEOUT_SECONDS 10 /* default for the whole request; --timeout changes it */

struct dataset {
    char id[SERVER_MAX_ID + 1];
    struct tilefile file;
};

/* 1 if `id` is a valid dataset id: 1 to 32 of a-z 0-9 - _. */
int server_valid_id(const char *id);

/* What a request asks for, from its method and target (path + query). Pure: no sockets. */
enum route_kind {
    ROUTE_DATASETS, /* GET /api/datasets */
    ROUTE_DATASET,  /* GET /api/datasets/{id} */
    ROUTE_TILE,     /* GET /tiles/{id}/{z}/{x}/{y}.png */
    ROUTE_NOT_FOUND,
    ROUTE_BAD_REQUEST,
    ROUTE_BAD_METHOD
};

struct route {
    enum route_kind kind;
    const struct dataset *dataset; /* ROUTE_DATASET, ROUTE_TILE */
    unsigned zoom;                 /* ROUTE_TILE */
    uint32_t x, y;
    const char *message; /* why, for the error kinds */
};

struct route server_route(const char *method, const char *target, const struct dataset *datasets, size_t count);

/* Listens on host:port (port 0: any free port) and serves until killed. A client has `timeout` seconds
 * to send its whole request, and 6 × timeout to read the answer. Prints "gpstiles serve: http://HOST:PORT/"
 * as the first line on stdout once listening. Returns 1 after printing why if it can't listen (it never
 * returns otherwise). */
int server_run(const char *host, unsigned port, unsigned timeout, const struct dataset *datasets, size_t count);

#endif
