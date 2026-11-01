.SUFFIXES:

ifeq ($(strip $(DEVKITARM)),)
$(error DEVKITARM is not set; install the devkitPro 3ds-dev group and use its environment)
endif

TOPDIR          ?= $(CURDIR)
include $(DEVKITARM)/3ds_rules

TARGET          := AMUN
BUILD           := build
SOURCES         := plugin memory identity runtime storage
INCLUDES        := include runtime storage ../core/include
PLGINFO         := AMUN.plgInfo
CORE_SOURCE_DIR := ../core/src
CORE_CPPFILES   := crc32.cpp memory.cpp pack.cpp runtime.cpp vm.cpp
CORE_LIBRARY    := $(TOPDIR)/lib/libamun_core.a

AMUN_DEPS_DIR   ?= $(abspath $(TOPDIR)/../build-3ds-deps)
CTRPFLIB        ?= $(AMUN_DEPS_DIR)/ctrpluginframework/Library
ifeq ($(origin THREEGXTOOL),undefined)
THREEGXTOOL_CANDIDATES := \
    $(AMUN_DEPS_DIR)/3gxtool-build/3gxtool \
    $(AMUN_DEPS_DIR)/3gxtool-build/3gxtool.exe \
    $(AMUN_DEPS_DIR)/3gxtool-build/Release/3gxtool.exe
THREEGXTOOL     := $(firstword $(wildcard $(THREEGXTOOL_CANDIDATES)))
ifeq ($(strip $(THREEGXTOOL)),)
THREEGXTOOL     := $(AMUN_DEPS_DIR)/3gxtool-build/3gxtool
endif
endif
CMAKE          ?= cmake
SHA256SUM      ?= sha256sum

ARCH            := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft
CFLAGS          := $(ARCH) -Os -g -mword-relocations -fomit-frame-pointer \
                   -ffunction-sections -fdata-sections -fno-strict-aliasing \
                   -Wall -Wextra -Wpedantic -Wconversion -Wshadow \
                   -D__3DS__ -DAMUN_3DS_NETWORKING=0 $(INCLUDE)
CXXFLAGS        := $(CFLAGS) -std=gnu++20 -fno-rtti -fno-exceptions \
                   -fno-threadsafe-statics -DAMUN_VERSION=\"0.1.0\"
ASFLAGS         := $(ARCH) -g
LDFLAGS         := -T $(TOPDIR)/3gx.ld $(ARCH) -g -Os \
                   -Wl,--gc-sections,--strip-discarded,-Map,$(TOPDIR)/$(TARGET).map

LIBS            := -lamun_core -lctrpf -lctru -lm
LIBDIRS         := $(TOPDIR) $(CTRPFLIB) $(CTRULIB) $(PORTLIBS)

ifneq ($(BUILD),$(notdir $(CURDIR)))

export OUTPUT   := $(CURDIR)/$(TARGET)
export TOPDIR   := $(CURDIR)
export VPATH    := $(foreach dir,$(SOURCES),$(CURDIR)/$(dir)) $(CURDIR)/$(CORE_SOURCE_DIR)
export DEPSDIR  := $(CURDIR)/$(BUILD)

CFILES          := $(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.c)))
CPPFILES        := $(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.cpp)))
SFILES          := $(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.s)))

export LD       := $(CXX)
export OFILES   := $(CPPFILES:.cpp=.o) $(CFILES:.c=.o) $(SFILES:.s=.o)
export CORE_OFILES := $(CORE_CPPFILES:.cpp=.o)
export INCLUDE  := $(foreach dir,$(INCLUDES),-I$(CURDIR)/$(dir)) \
                   $(foreach dir,$(LIBDIRS),-isystem$(dir)/include) \
                   -I$(CURDIR)/$(BUILD)
export LIBPATHS := $(foreach dir,$(LIBDIRS),-L$(dir)/lib)

.PHONY: all clean package check-deps

all: $(BUILD)

check-deps:
	@test -f "$(CTRPFLIB)/lib/libctrpf.a" || \
	  (echo "Missing pinned libctrpf.a. Follow docs/3ds-toolchain.md." && exit 1)
	@test -x "$(THREEGXTOOL)" || \
	  (echo "Missing pinned 3gxtool: $(THREEGXTOOL)" && exit 1)

$(BUILD): check-deps
	@mkdir -p $@
	@$(MAKE) --no-print-directory -C $(BUILD) -f $(CURDIR)/Makefile

package: all
	@mkdir -p "$(CURDIR)/../dist/sd-root/luma/plugins"
	@mkdir -p "$(CURDIR)/../dist/sd-root/amun/packs"
	@mkdir -p "$(CURDIR)/../dist/sd-root/amun/ledger"
	@mkdir -p "$(CURDIR)/../dist/sd-root/amun/logs"
	@mkdir -p "$(CURDIR)/../dist/sd-root/amun/config"
	@cp "$(CURDIR)/config/self-test.flag.example" \
	    "$(CURDIR)/../dist/sd-root/amun/config/self-test.flag.example"
	@cp "$(OUTPUT).3gx" "$(CURDIR)/../dist/sd-root/luma/plugins/default.3gx"
	@mkdir -p "$(CURDIR)/../dist/dev"
	@cp "$(OUTPUT).3gx" "$(OUTPUT).elf" "$(OUTPUT).map" \
	    "$(CURDIR)/../dist/dev/"
	@cp "$(CURDIR)/BUILD-STATUS.txt" "$(CURDIR)/../dist/dev/BUILD-STATUS.txt"
	@cd "$(CURDIR)/../dist/dev" && \
	    "$(SHA256SUM)" AMUN.3gx AMUN.elf AMUN.map > SHA256SUMS

clean:
	@rm -rf "$(BUILD)" "$(OUTPUT).3gx" "$(OUTPUT).elf" "$(OUTPUT).map" \
	          "$(CURDIR)/lib/libamun_core.a"

else

DEPENDS := $(OFILES:.o=.d) $(CORE_OFILES:.o=.d)

$(OUTPUT).3gx: $(OFILES) $(CORE_LIBRARY)
$(OUTPUT).elf: $(OFILES) $(CORE_LIBRARY)

$(CORE_LIBRARY): $(CORE_OFILES)
	@mkdir -p "$(dir $@)"
	@echo "archiving $(notdir $@)"
	@$(AR) rcs "$@" $(CORE_OFILES)

.PRECIOUS: %.elf
%.3gx: %.elf
	@echo "creating $(notdir $@)"
	@"$(THREEGXTOOL)" --silent "$<" "$(TOPDIR)/$(PLGINFO)" "$@"
	@"$(CMAKE)" -DAMUN_3GX="$@" -P "$(TOPDIR)/../cmake/3ds/verify_3gx.cmake"

-include $(DEPENDS)

endif
