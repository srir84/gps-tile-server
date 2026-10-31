/* www.h: the map page and Leaflet (www/), compiled in by tools/embed.sh and served by server.c. */
#ifndef WWW_H
#define WWW_H

#include <stddef.h>

struct www_file {
    const char *path; /* URL path: "/" for www/index.html, "/leaflet/leaflet.js", ... */
    const char *type; /* Content-Type */
    const unsigned char *data;
    size_t size;
};

extern const struct www_file www_files[];
extern const size_t www_file_count;

#endif
