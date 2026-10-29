# Makefile: builds gpstiles and runs the checks (AGENTS.md "Commands").
# Must work with GNU Make 3.81, the version on macOS: no .ONESHELL, $(file ...) or grouped targets.

CC     ?= cc
PYTHON ?= python3
WARN   := -std=c11 -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Werror
CFLAGS ?= -O2 -g
SANITIZE_FLAGS := -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer

# `make sanitize` re-runs this Makefile with B=build/san and MODE_FLAGS=$(SANITIZE_FLAGS).
B          ?= build
MODE_FLAGS ?= $(CFLAGS)
ALL_CFLAGS  = $(WARN) $(MODE_FLAGS) -MMD -MP -Isrc -Itests

SRC      := $(wildcard src/*.c)
LIB_SRC  := $(filter-out src/main.c,$(SRC))
UNIT_SRC := $(wildcard tests/unit/*.c) tests/check.c

BIN      := $(B)/gpstiles
UNIT_BIN := $(B)/tests/unit
SELF_BIN := $(B)/tests/always_fails

objects = $(patsubst %.c,$(B)/obj/%.o,$(1))

# Everything is rebuilt when the compiler or its flags change, so `make sanitize` can never
# reuse objects built without sanitizers. The stamp is rewritten only when its text differs.
BUILD_CONFIG := $(CC) $(ALL_CFLAGS) $(LDLIBS)
CONFIG_STAMP := $(B)/.build-config
$(shell mkdir -p $(B) && echo '$(BUILD_CONFIG)' | cmp -s - $(CONFIG_STAMP) || echo '$(BUILD_CONFIG)' > $(CONFIG_STAMP))

all: $(BIN)

$(BIN): $(call objects,$(SRC))
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -o $@ $^ $(LDLIBS)

$(UNIT_BIN): $(call objects,$(LIB_SRC) $(UNIT_SRC))
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -o $@ $^ $(LDLIBS)

$(SELF_BIN): $(call objects,tests/selftest/always_fails.c tests/check.c)
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -o $@ $^

$(B)/obj/%.o: %.c $(CONFIG_STAMP)
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -c -o $@ $<

check: $(BIN) $(UNIT_BIN) $(SELF_BIN)
	@$(UNIT_BIN)
	@GPSTILES_BIN=$(BIN) CHECK_SELFTEST_BIN=$(SELF_BIN) $(PYTHON) -I -B tests/e2e/run.py
	@echo "ALL PASSED ($(B))"

sanitize:
	@$(MAKE) --no-print-directory check B=build/san MODE_FLAGS="$(SANITIZE_FLAGS)"

clean:
	rm -rf build

-include $(patsubst %.c,$(B)/obj/%.d,$(SRC) $(UNIT_SRC) tests/selftest/always_fails.c)

.PHONY: all check sanitize clean
