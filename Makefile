# Build helpers + .app + zip using system python3 (no venv).
SDK ?= $(shell xcrun --sdk macosx --show-sdk-path)
CC ?= clang
# Universal helpers so one zip works on Apple Silicon and Intel.
ARCHS ?= -arch arm64 -arch x86_64
NVME_OUT = ssdinfo/bin/nvme_health
NVME_SRC = native/nvme_health.c
SMC_OUT = ssdinfo/bin/smc_thermal
SMC_SRC = native/smc_thermal.c
APP_NAME = Mac Hardware Info
VERSION = 0.3.1
ZIP = dist/MacHardwareInfo-$(VERSION)-macos.zip
PYTHON ?= python3

.PHONY: helper clean clean-dist app zip release

helper: $(NVME_OUT) $(SMC_OUT)

$(NVME_OUT): $(NVME_SRC)
	mkdir -p ssdinfo/bin
	$(CC) -O2 -Wall -Wextra $(ARCHS) -isysroot "$(SDK)" \
		-mmacosx-version-min=14.0 \
		-framework IOKit -framework CoreFoundation \
		-o "$@" "$<"

$(SMC_OUT): $(SMC_SRC)
	mkdir -p ssdinfo/bin
	$(CC) -O2 -Wall -Wextra $(ARCHS) -isysroot "$(SDK)" \
		-mmacosx-version-min=14.0 \
		-framework IOKit -framework CoreFoundation \
		-o "$@" "$<"

# Build .app with py2app
app: helper
	rm -rf build dist
	$(PYTHON) setup.py py2app
	@# Ad-hoc sign so local Gatekeeper is less noisy; Developer ID still needed for notarized downloads.
	codesign --force --deep --sign - "dist/$(APP_NAME).app" 2>/dev/null || true
	@echo "Bundle ID: $$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' 'dist/$(APP_NAME).app/Contents/Info.plist')"
	@file "ssdinfo/bin/nvme_health" "ssdinfo/bin/smc_thermal"

# Zip existing .app for distribution
zip:
	@test -d "dist/$(APP_NAME).app" || (echo "Missing dist/$(APP_NAME).app — run: make app"; exit 1)
	cd dist && rm -f "MacHardwareInfo-$(VERSION)-macos.zip" && \
		zip -r "MacHardwareInfo-$(VERSION)-macos.zip" "$(APP_NAME).app"
	@ls -lh "$(ZIP)"

# Full distribute: helper + .app + zip
release: app zip
	@echo ""
	@echo "Ready to distribute:"
	@echo "  App: $(CURDIR)/dist/$(APP_NAME).app"
	@echo "  Zip: $(CURDIR)/$(ZIP)"
	@echo "  Note: unsigned / ad-hoc only. For Gatekeeper-clean downloads, codesign + notarize with a Developer ID."

clean:
	rm -f "$(NVME_OUT)" "$(SMC_OUT)"

clean-dist:
	rm -rf build dist
