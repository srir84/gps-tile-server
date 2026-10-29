/* gpstiles: command-line entry point. Commands are added step by step (DESIGN §9.1).
 * Exit codes: 0 = ok, 2 = usage error (unknown command, bad arguments). Errors are one line on stderr. */
#include <stdio.h>
#include <string.h>

/* Copies at most size-1 bytes of an untrusted argument, replacing control characters with '?',
 * so echoing it can't split the error over several lines or send terminal escape codes. */
static void printable_copy(char *out, size_t size, const char *in)
{
    size_t n = 0;
    for (; n + 1 < size && in[n] != '\0'; n++) {
        unsigned char c = (unsigned char)in[n];
        out[n] = (c < 0x20 || c == 0x7f) ? '?' : (char)c;
    }
    out[n] = '\0';
}

static void print_usage(void)
{
    fputs("usage: gpstiles <command> [arguments]\n"
          "\n"
          "commands:\n"
          "  help    show this message\n",
          stdout);
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fputs("gpstiles: missing command (try 'gpstiles help')\n", stderr);
        return 2;
    }
    if (strcmp(argv[1], "help") == 0 || strcmp(argv[1], "--help") == 0) {
        print_usage();
        return 0;
    }
    char name[65];
    printable_copy(name, sizeof name, argv[1]);
    fprintf(stderr, "gpstiles: unknown command '%s' (try 'gpstiles help')\n", name);
    return 2;
}
