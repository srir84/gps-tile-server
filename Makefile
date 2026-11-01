# Makefile: builds gpstiles and runs the checks (AGENTS.md "Commands").
# Must work with GNU Make 3.81, the version on macOS: no .ONESHELL, $(file ...) or grouped targets.

CC     ?= cc
PYTHON ?= python3
WARN   := -std=c11 -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Werror
CFLAGS ?= -O2 -g
LDLIBS += -lm -lz
SANITIZE_FLAGS := -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer

# `make sanitize` re-runs this Makefile with B=build/san and MODE_FLAGS=$(SANITIZE_FLAGS).
B          ?= build
MODE_FLAGS ?= $(CFLAGS)
ALL_CFLAGS  = $(WARN) $(MODE_FLAGS) -MMD -MP -Isrc -Itests

SRC      := $(wildcard src/*.c)
LIB_SRC  := $(filter-out src/main.c,$(SRC))
UNIT_SRC := $(wildcard tests/unit/*.c) tests/check.c

# The map page and Leaflet, compiled into the program (src/www.h, tools/embed.sh).
WWW      := www/index.html www/app.css www/app.js www/leaflet/leaflet.css www/leaflet/leaflet.js
WWW_OBJ  := $(B)/obj/www.o

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

$(BIN): $(call objects,$(SRC)) $(WWW_OBJ)
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -o $@ $^ $(LDLIBS)

$(UNIT_BIN): $(call objects,$(LIB_SRC) $(UNIT_SRC)) $(WWW_OBJ)
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -o $@ $^ $(LDLIBS)

$(SELF_BIN): $(call objects,tests/selftest/always_fails.c tests/check.c)
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -o $@ $^

$(B)/gen/www.c: $(WWW) tools/embed.sh
	@mkdir -p $(dir $@)
	sh tools/embed.sh $(WWW) > $@.tmp && mv $@.tmp $@

$(WWW_OBJ): $(B)/gen/www.c src/www.h $(CONFIG_STAMP)
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -c -o $@ $<

$(B)/obj/%.o: %.c $(CONFIG_STAMP)
	@mkdir -p $(dir $@)
	$(CC) $(ALL_CFLAGS) -c -o $@ $<

check: $(BIN) $(UNIT_BIN) $(SELF_BIN)
	@$(UNIT_BIN)
	@GPSTILES_BIN=$(BIN) CHECK_SELFTEST_BIN=$(SELF_BIN) $(PYTHON) -I -B tests/e2e/run.py
	@echo "ALL PASSED ($(B))"

sanitize:
	@$(MAKE) --no-print-directory check B=build/san MODE_FLAGS="$(SANITIZE_FLAGS)"

# Real T-Drive checks against awk and Python (TESTING.md level 6). SKIPPED without data/.
check-data: $(BIN)
	@GPSTILES_BIN=$(BIN) $(PYTHON) -I -B tests/data/check_tdrive.py

# Everything, in order, stopping at the first red part (TESTING.md §12.1).
VALIDATE := $(sort $(wildcard tests/validate/step-*.sh))

verify:
	@$(MAKE) --no-print-directory check || { echo "VERIFY FAILED at: make check"; exit 1; }
	@$(MAKE) --no-print-directory sanitize || { echo "VERIFY FAILED at: make sanitize"; exit 1; }
	@$(MAKE) --no-print-directory check-data || { echo "VERIFY FAILED at: make check-data"; exit 1; }
	@for script in $(VALIDATE); do \
		echo "--- $$script"; \
		bash "$$script" || { echo "VERIFY FAILED at: $$script"; exit 1; }; \
	done
	@echo "VERIFY PASSED"

# Local service on this Mac (TESTING.md §12.6). deploy-test is the pre-approval check: build/deploy-test/,
# test label, free port, removed afterwards. The others act on the real service: after approval only.
deploy-test: $(BIN)
	@bash tools/deploy-test.sh

deploy: check
	@bash tools/deploy.sh deploy

rollback:
	@bash tools/deploy.sh rollback

undeploy:
	@bash tools/deploy.sh undeploy

status:
	@bash tools/deploy.sh status

# A package others can install (TESTING.md §12.7). release-test is the pre-approval check: the package and
# its smoke test in build/release-test/, no tag. release: dist/ + .sha256 + a local tag, after approval only.
release-test:
	@bash tools/release.sh test

# VERSION reaches the script through the environment, quoted by the shell: never pasted into the command.
release: export RELEASE_VERSION = $(VERSION)
release:
	@test -n "$$RELEASE_VERSION" || { echo "usage: make release VERSION=x.y.z"; exit 2; }
	@bash tools/release.sh "$$RELEASE_VERSION"

# Links .git/hooks/pre-commit to tools/pre-commit. Never replaces a hook that isn't ours.
hooks:
	@hook="$$(git rev-parse --git-path hooks)/pre-commit"; \
	if { [ -e "$$hook" ] || [ -L "$$hook" ]; } && [ "$$(readlink "$$hook")" != "$(CURDIR)/tools/pre-commit" ]; then \
		echo "make hooks: $$hook already exists and is not ours. Not replacing it."; exit 1; \
	fi; \
	ln -sf "$(CURDIR)/tools/pre-commit" "$$hook" && echo "make hooks: $$hook -> tools/pre-commit"

clean:
	rm -rf build

-include $(patsubst %.c,$(B)/obj/%.d,$(SRC) $(UNIT_SRC) tests/selftest/always_fails.c)

.PHONY: all check sanitize check-data verify hooks clean deploy-test deploy rollback undeploy status release-test release
