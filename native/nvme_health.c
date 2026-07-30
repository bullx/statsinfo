/*
 * Read NVMe SMART/Health via Apple IONVMeSMARTInterface (IOKit).
 * No smartctl — same kernel user-client Apple exposes to utilities.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/storage/nvme/NVMeSMARTLibExternal.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>

static uint64_t u128_low(const uint64_t v[2]) {
    return v[0];
}

static void json_escape(const char *s, char *out, size_t n) {
    size_t j = 0;
    for (size_t i = 0; s[i] && j + 2 < n; i++) {
        char c = s[i];
        if (c == '"' || c == '\\') {
            if (j + 3 >= n) break;
            out[j++] = '\\';
            out[j++] = c;
        } else if ((unsigned char)c < 0x20) {
            continue;
        } else {
            out[j++] = c;
        }
    }
    out[j] = '\0';
}

static void trim_copy(const uint8_t *src, size_t len, char *dst, size_t dstlen) {
    size_t i = 0;
    while (i < len && src[i] == ' ') i++;
    size_t end = len;
    while (end > i && src[end - 1] == ' ') end--;
    size_t n = end - i;
    if (n >= dstlen) n = dstlen - 1;
    memcpy(dst, src + i, n);
    dst[n] = '\0';
}

static int read_one(io_service_t service, int *first) {
    IOCFPlugInInterface **plugin = NULL;
    SInt32 score = 0;
    kern_return_t kr = IOCreatePlugInInterfaceForService(
        service,
        kIONVMeSMARTUserClientTypeID,
        kIOCFPlugInInterfaceID,
        &plugin,
        &score);
    if (kr != kIOReturnSuccess || plugin == NULL) {
        return 0;
    }

    IONVMeSMARTInterface **smart = NULL;
    HRESULT hr = (*plugin)->QueryInterface(
        plugin,
        CFUUIDGetUUIDBytes(kIONVMeSMARTInterfaceID),
        (LPVOID *)&smart);
    if (hr != S_OK || smart == NULL) {
        IODestroyPlugInInterface(plugin);
        return 0;
    }

    NVMeSMARTData data;
    memset(&data, 0, sizeof(data));
    IOReturn rr = (*smart)->SMARTReadData(smart, &data);

    char serial[64] = "";
    char model[80] = "";
    char firmware[32] = "";
    NVMeIdentifyControllerStruct id;
    memset(&id, 0, sizeof(id));
    if ((*smart)->GetIdentifyData(smart, &id, 0) == kIOReturnSuccess) {
        trim_copy(id.SERIAL_NUMBER, sizeof(id.SERIAL_NUMBER), serial, sizeof(serial));
        trim_copy(id.MODEL_NUMBER, sizeof(id.MODEL_NUMBER), model, sizeof(model));
        trim_copy(id.FW_REVISION, sizeof(id.FW_REVISION), firmware, sizeof(firmware));
    }

    /* Prefer BSD name from this node or children */
    char bsd[32] = "";
    CFTypeRef bsdRef = IORegistryEntryCreateCFProperty(service, CFSTR("BSD Name"), kCFAllocatorDefault, 0);
    if (!bsdRef) {
        io_iterator_t childIter;
        if (IORegistryEntryGetChildIterator(service, kIOServicePlane, &childIter) == KERN_SUCCESS) {
            io_object_t child;
            while ((child = IOIteratorNext(childIter)) != 0) {
                CFTypeRef r = IORegistryEntryCreateCFProperty(child, CFSTR("BSD Name"), kCFAllocatorDefault, 0);
                if (r) {
                    bsdRef = r;
                    IOObjectRelease(child);
                    break;
                }
                IOObjectRelease(child);
            }
            IOObjectRelease(childIter);
        }
    }
    if (bsdRef && CFGetTypeID(bsdRef) == CFStringGetTypeID()) {
        CFStringGetCString((CFStringRef)bsdRef, bsd, sizeof(bsd), kCFStringEncodingUTF8);
    }
    if (bsdRef) CFRelease(bsdRef);

    if (rr == kIOReturnSuccess) {
        char esc_model[160], esc_serial[128], esc_fw[64], esc_bsd[64];
        json_escape(model, esc_model, sizeof(esc_model));
        json_escape(serial, esc_serial, sizeof(esc_serial));
        json_escape(firmware, esc_fw, sizeof(esc_fw));
        json_escape(bsd, esc_bsd, sizeof(esc_bsd));

        int temp_c = (int)data.TEMPERATURE - 273;
        uint64_t dur = u128_low(data.DATA_UNITS_READ);
        uint64_t duw = u128_low(data.DATA_UNITS_WRITTEN);
        uint64_t hr_c = u128_low(data.HOST_READ_COMMANDS);
        uint64_t hw_c = u128_low(data.HOST_WRITE_COMMANDS);
        uint64_t cbt = u128_low(data.CONTROLLER_BUSY_TIME);
        uint64_t pc = u128_low(data.POWER_CYCLES);
        uint64_t poh = u128_low(data.POWER_ON_HOURS);
        uint64_t us = u128_low(data.UNSAFE_SHUTDOWNS);
        uint64_t me = u128_low(data.MEDIA_ERRORS);
        uint64_t eil = u128_low(data.NUM_ERROR_INFO_LOG_ENTRIES);

        if (!*first) fputs(",\n", stdout);
        *first = 0;
        printf(
            "  {"
            "\"bsd_name\":\"%s\","
            "\"model\":\"%s\","
            "\"serial\":\"%s\","
            "\"firmware\":\"%s\","
            "\"critical_warning\":%u,"
            "\"temperature_c\":%d,"
            "\"available_spare\":%u,"
            "\"available_spare_threshold\":%u,"
            "\"percentage_used\":%u,"
            "\"data_units_read\":%" PRIu64 ","
            "\"data_units_written\":%" PRIu64 ","
            "\"host_reads\":%" PRIu64 ","
            "\"host_writes\":%" PRIu64 ","
            "\"controller_busy_time\":%" PRIu64 ","
            "\"power_cycles\":%" PRIu64 ","
            "\"power_on_hours\":%" PRIu64 ","
            "\"unsafe_shutdowns\":%" PRIu64 ","
            "\"media_errors\":%" PRIu64 ","
            "\"num_err_log_entries\":%" PRIu64
            "}",
            esc_bsd, esc_model, esc_serial, esc_fw,
            (unsigned)data.CRITICAL_WARNING,
            temp_c,
            (unsigned)data.AVAILABLE_SPARE,
            (unsigned)data.AVAILABLE_SPARE_THRESHOLD,
            (unsigned)data.PERCENTAGE_USED,
            dur, duw, hr_c, hw_c, cbt, pc, poh, us, me, eil);
    }

    (*smart)->Release(smart);
    IODestroyPlugInInterface(plugin);
    return rr == kIOReturnSuccess ? 1 : 0;
}

int main(void) {
    /* Match any IOKit service advertising NVMe SMART Capable */
    CFMutableDictionaryRef matching = IOServiceMatching("IOBlockStorageDevice");
    if (!matching) {
        fputs("{\"drives\":[],\"error\":\"matching failed\"}\n", stdout);
        return 1;
    }

    io_iterator_t iter = 0;
    kern_return_t kr = IOServiceGetMatchingServices(kIOMainPortDefault, matching, &iter);
    if (kr != KERN_SUCCESS) {
        /* older SDK alias */
        kr = IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOBlockStorageDevice"), &iter);
    }
    if (kr != KERN_SUCCESS) {
        fputs("{\"drives\":[],\"error\":\"iterator failed\"}\n", stdout);
        return 1;
    }

    fputs("{\"drives\":[\n", stdout);
    int first = 1;
    int found = 0;
    io_service_t service;
    while ((service = IOIteratorNext(iter)) != 0) {
        CFTypeRef capable = IORegistryEntryCreateCFProperty(
            service, CFSTR(kIOPropertyNVMeSMARTCapableKey), kCFAllocatorDefault, 0);
        int ok = 0;
        if (capable) {
            if (CFGetTypeID(capable) == CFBooleanGetTypeID() && CFBooleanGetValue((CFBooleanRef)capable)) {
                ok = 1;
            }
            CFRelease(capable);
        }
        if (ok) {
            if (read_one(service, &first)) found++;
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iter);

    /* Fallback: try IONVMeBlockStorageDevice class directly */
    if (found == 0) {
        matching = IOServiceMatching("IONVMeBlockStorageDevice");
        if (matching &&
            IOServiceGetMatchingServices(kIOMainPortDefault, matching, &iter) == KERN_SUCCESS) {
            while ((service = IOIteratorNext(iter)) != 0) {
                if (read_one(service, &first)) found++;
                IOObjectRelease(service);
            }
            IOObjectRelease(iter);
        }
    }

    fputs("\n]}\n", stdout);
    return found > 0 ? 0 : 2;
}
