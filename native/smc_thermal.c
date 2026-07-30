/*
 * Apple Silicon thermal / fan helper via AppleSMC (IOKit).
 * Original implementation for Mac Hardware Info.
 *
 * Commands:
 *   (no args) | status     JSON snapshot (sensors + fans)
 *   auto                   restore system fan control
 *   set <index> <rpm>      manual target RPM for one fan
 *   daemon --state <path>  privileged loop: follow state JSON until stop
 *
 * Writes require root. Always clamps to SMC min/max; emergency boost on hot die.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>

#include <errno.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <unistd.h>

enum {
    kSMCIndex = 2,
    kSMCReadBytes = 5,
    kSMCWriteBytes = 6,
    kSMCReadKeyInfo = 9,
};

typedef struct {
    uint32_t dataSize;
    uint32_t dataType;
    uint8_t dataAttributes;
} SMCKeyInfo;

typedef struct {
    uint32_t key;
    uint8_t vers[6];
    uint8_t plimit[16];
    SMCKeyInfo keyInfo;
    uint8_t result;
    uint8_t status;
    uint8_t data8;
    uint32_t data32;
    uint8_t bytes[32];
} SMCPacket;

static io_connect_t g_conn = IO_OBJECT_NULL;
static volatile sig_atomic_t g_stop = 0;

static uint32_t fourcc(const char *s) {
    return ((uint32_t)(uint8_t)s[0] << 24) | ((uint32_t)(uint8_t)s[1] << 16) |
           ((uint32_t)(uint8_t)s[2] << 8) | (uint32_t)(uint8_t)s[3];
}

static void type_to_str(uint32_t t, char out[5]) {
    out[0] = (char)((t >> 24) & 0xff);
    out[1] = (char)((t >> 16) & 0xff);
    out[2] = (char)((t >> 8) & 0xff);
    out[3] = (char)(t & 0xff);
    out[4] = '\0';
}

static int is_apple_silicon(void) {
    int arm = 0;
    size_t n = sizeof(arm);
    if (sysctlbyname("hw.optional.arm64", &arm, &n, NULL, 0) == 0 && arm == 1) {
        return 1;
    }
#if defined(__arm64__) || defined(__aarch64__)
    return 1;
#else
    return 0;
#endif
}

static int smc_open(void) {
    io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("AppleSMC"));
    if (!service) {
        return -1;
    }
    kern_return_t kr = IOServiceOpen(service, mach_task_self(), 0, &g_conn);
    IOObjectRelease(service);
    return (kr == KERN_SUCCESS && g_conn != IO_OBJECT_NULL) ? 0 : -1;
}

static void smc_close(void) {
    if (g_conn != IO_OBJECT_NULL) {
        IOServiceClose(g_conn);
        g_conn = IO_OBJECT_NULL;
    }
}

static int smc_call(SMCPacket *in, SMCPacket *out) {
    size_t out_size = sizeof(*out);
    kern_return_t kr = IOConnectCallStructMethod(g_conn, kSMCIndex, in, sizeof(*in), out, &out_size);
    return kr == KERN_SUCCESS ? 0 : -1;
}

static int smc_key_info(uint32_t key, SMCKeyInfo *info) {
    SMCPacket in, out;
    memset(&in, 0, sizeof(in));
    memset(&out, 0, sizeof(out));
    in.key = key;
    in.data8 = kSMCReadKeyInfo;
    if (smc_call(&in, &out) != 0) {
        return -1;
    }
    *info = out.keyInfo;
    return out.result == 0 ? 0 : -1;
}

static int smc_read(uint32_t key, uint8_t *bytes, uint32_t *size, uint32_t *type) {
    SMCKeyInfo info;
    if (smc_key_info(key, &info) != 0) {
        return -1;
    }
    SMCPacket in, out;
    memset(&in, 0, sizeof(in));
    memset(&out, 0, sizeof(out));
    in.key = key;
    in.keyInfo = info;
    in.data8 = kSMCReadBytes;
    if (smc_call(&in, &out) != 0 || out.result != 0) {
        return -1;
    }
    uint32_t n = info.dataSize;
    if (n > 32) {
        n = 32;
    }
    memcpy(bytes, out.bytes, n);
    if (size) {
        *size = n;
    }
    if (type) {
        *type = info.dataType;
    }
    return 0;
}

static int smc_write(uint32_t key, const uint8_t *bytes, uint32_t size) {
    SMCKeyInfo info;
    if (smc_key_info(key, &info) != 0) {
        return -1;
    }
    if (size > info.dataSize) {
        size = info.dataSize;
    }
    SMCPacket in, out;
    memset(&in, 0, sizeof(in));
    memset(&out, 0, sizeof(out));
    in.key = key;
    in.keyInfo.dataSize = size;
    in.keyInfo.dataType = info.dataType;
    in.data8 = kSMCWriteBytes;
    memcpy(in.bytes, bytes, size);
    if (smc_call(&in, &out) != 0) {
        return -1;
    }
    return out.result == 0 ? 0 : -1;
}

static float decode_value(const uint8_t *b, uint32_t size, uint32_t type) {
    char ts[5];
    type_to_str(type, ts);
    if (strcmp(ts, "flt ") == 0 && size >= 4) {
        float f;
        memcpy(&f, b, 4);
        return f;
    }
    if ((strcmp(ts, "ui8 ") == 0 || strcmp(ts, "hex_") == 0) && size >= 1) {
        return (float)b[0];
    }
    if (strcmp(ts, "ui16") == 0 && size >= 2) {
        return (float)((b[0] << 8) | b[1]);
    }
    if (strcmp(ts, "sp78") == 0 && size >= 2) {
        int16_t v = (int16_t)((b[0] << 8) | b[1]);
        return (float)v / 256.0f;
    }
    if (size >= 2) {
        /* fan RPM sometimes packed as big-endian ui16 */
        return (float)((b[0] << 8) | b[1]);
    }
    if (size == 1) {
        return (float)b[0];
    }
    return NAN;
}

static int read_float_key(const char *name, float *out) {
    uint8_t bytes[32];
    uint32_t size = 0, type = 0;
    if (smc_read(fourcc(name), bytes, &size, &type) != 0) {
        return -1;
    }
    float v = decode_value(bytes, size, type);
    if (isnan(v)) {
        return -1;
    }
    *out = v;
    return 0;
}

static int write_numeric(const char *name, float value) {
    SMCKeyInfo info;
    uint32_t key = fourcc(name);
    if (smc_key_info(key, &info) != 0) {
        return -1;
    }
    char ts[5];
    type_to_str(info.dataType, ts);
    uint8_t bytes[32];
    memset(bytes, 0, sizeof(bytes));
    uint32_t size = info.dataSize;
    if (size == 0 || size > 32) {
        size = 4;
    }

    if (strcmp(ts, "flt ") == 0) {
        float f = value;
        memcpy(bytes, &f, 4);
        size = 4;
    } else if (strcmp(ts, "ui8 ") == 0 || strcmp(ts, "hex_") == 0 || size == 1) {
        bytes[0] = (uint8_t)(value < 0 ? 0 : value + 0.5f);
        size = 1;
    } else if (strcmp(ts, "ui16") == 0 || size == 2) {
        uint16_t v = (uint16_t)(value < 0 ? 0 : value + 0.5f);
        bytes[0] = (uint8_t)(v >> 8);
        bytes[1] = (uint8_t)(v & 0xff);
        size = 2;
    } else {
        float f = value;
        memcpy(bytes, &f, 4);
        if (size > 4) {
            size = 4;
        }
    }
    return smc_write(key, bytes, size);
}

static int fan_key(char *buf, size_t n, int index, const char *suffix) {
    if (index < 0 || index > 9) {
        return -1;
    }
    return snprintf(buf, n, "F%d%s", index, suffix) > 0 ? 0 : -1;
}

static int try_diagnostic_unlock(void) {
    if (write_numeric("Ftst", 1.0f) == 0) {
        usleep(50000);
        return 0;
    }
    uint8_t one = 1;
    if (smc_write(fourcc("Ftst"), &one, 1) == 0) {
        usleep(50000);
        return 0;
    }
    return -1;
}

static int set_fan_manual(int index, float rpm) {
    char k_md[8], k_tg[8], k_mn[8], k_mx[8];
    if (fan_key(k_md, sizeof(k_md), index, "Md") != 0 ||
        fan_key(k_tg, sizeof(k_tg), index, "Tg") != 0 ||
        fan_key(k_mn, sizeof(k_mn), index, "Mn") != 0 ||
        fan_key(k_mx, sizeof(k_mx), index, "Mx") != 0) {
        return -1;
    }

    float mn = 0, mx = 0;
    if (read_float_key(k_mn, &mn) != 0) {
        mn = 1000;
    }
    if (read_float_key(k_mx, &mx) != 0) {
        mx = 6000;
    }
    if (rpm < mn) {
        rpm = mn;
    }
    if (rpm > mx) {
        rpm = mx;
    }

    /* Prefer typed writes; unlock then retry if mode write fails. */
    if (write_numeric(k_md, 1.0f) != 0) {
        try_diagnostic_unlock();
        if (write_numeric(k_md, 1.0f) != 0) {
            return -1;
        }
    }
    usleep(20000);
    if (write_numeric(k_tg, rpm) != 0) {
        return -1;
    }
    return 0;
}

static int set_fan_auto(int index) {
    char k_md[8];
    if (fan_key(k_md, sizeof(k_md), index, "Md") != 0) {
        return -1;
    }
    /* Mode 0 = auto on many machines; 3 = system-managed on others. */
    if (write_numeric(k_md, 0.0f) == 0) {
        return 0;
    }
    return write_numeric(k_md, 3.0f);
}

static int fan_count(void) {
    float n = 0;
    if (read_float_key("FNum", &n) != 0) {
        return 0;
    }
    int c = (int)(n + 0.5f);
    if (c < 0) {
        c = 0;
    }
    if (c > 8) {
        c = 8;
    }
    return c;
}

typedef struct {
    const char *key;
    const char *label;
} SensorMap;

static const SensorMap kSensors[] = {
    {"Tp01", "CPU 1"},
    {"Tp05", "CPU 2"},
    {"Tp09", "CPU 3"},
    {"Tp0b", "CPU 4"},
    {"Tp0d", "CPU 5"},
    {"Tg0a", "GPU A"},
    {"Tg0b", "GPU B"},
    {"Tg0f", "GPU Die"},
    {"Tg0H", "GPU Hotspot"},
    {"Ts0P", "Skin"},
    {"TW0P", "Wireless"},
    {"TaLP", "Ambient L"},
    {"TaRP", "Ambient R"},
    {"TH0a", "NAND A"},
    {"TH0b", "NAND B"},
    {"TH0x", "SSD"},
    {"TB1T", "Battery"},
    {NULL, NULL},
};

static float hottest_tracked(void) {
    float hot = -1000.0f;
    for (int i = 0; kSensors[i].key; i++) {
        float t;
        if (read_float_key(kSensors[i].key, &t) == 0 && t > hot && t < 200.0f) {
            hot = t;
        }
    }
    return hot;
}

static void print_status_json(void) {
    int fans = fan_count();
    printf("{\n");
    printf("  \"apple_silicon\": %s,\n", is_apple_silicon() ? "true" : "false");
    printf("  \"fanless\": %s,\n", fans <= 0 ? "true" : "false");
    printf("  \"fan_count\": %d,\n", fans);
    printf("  \"privileged\": %s,\n", (geteuid() == 0) ? "true" : "false");

    printf("  \"sensors\": [\n");
    int first_s = 1;
    float cpu = NAN, gpu = NAN, hot = NAN;
    for (int i = 0; kSensors[i].key; i++) {
        float t;
        if (read_float_key(kSensors[i].key, &t) != 0 || t < -50 || t > 150) {
            continue;
        }
        if (!first_s) {
            printf(",\n");
        }
        first_s = 0;
        printf("    {\"key\": \"%s\", \"label\": \"%s\", \"celsius\": %.2f}", kSensors[i].key,
               kSensors[i].label, t);
        if (strncmp(kSensors[i].key, "Tp", 2) == 0) {
            if (isnan(cpu) || t > cpu) {
                cpu = t;
            }
        }
        if (strncmp(kSensors[i].key, "Tg", 2) == 0) {
            if (isnan(gpu) || t > gpu) {
                gpu = t;
            }
        }
        if (isnan(hot) || t > hot) {
            hot = t;
        }
    }
    printf("\n  ],\n");

    printf("  \"summary\": {");
    printf("\"cpu_c\": ");
    if (isnan(cpu)) {
        printf("null");
    } else {
        printf("%.2f", cpu);
    }
    printf(", \"gpu_c\": ");
    if (isnan(gpu)) {
        printf("null");
    } else {
        printf("%.2f", gpu);
    }
    printf(", \"hottest_c\": ");
    if (isnan(hot)) {
        printf("null");
    } else {
        printf("%.2f", hot);
    }
    printf("},\n");

    printf("  \"fans\": [\n");
    for (int i = 0; i < fans; i++) {
        char k_ac[8], k_mn[8], k_mx[8], k_tg[8], k_md[8];
        fan_key(k_ac, sizeof(k_ac), i, "Ac");
        fan_key(k_mn, sizeof(k_mn), i, "Mn");
        fan_key(k_mx, sizeof(k_mx), i, "Mx");
        fan_key(k_tg, sizeof(k_tg), i, "Tg");
        fan_key(k_md, sizeof(k_md), i, "Md");
        float ac = NAN, mn = NAN, mx = NAN, tg = NAN, md = NAN;
        read_float_key(k_ac, &ac);
        read_float_key(k_mn, &mn);
        read_float_key(k_mx, &mx);
        read_float_key(k_tg, &tg);
        read_float_key(k_md, &md);
        printf("    {\"index\": %d", i);
        printf(", \"rpm\": ");
        if (isnan(ac)) {
            printf("null");
        } else {
            printf("%.0f", ac);
        }
        printf(", \"min_rpm\": ");
        if (isnan(mn)) {
            printf("null");
        } else {
            printf("%.0f", mn);
        }
        printf(", \"max_rpm\": ");
        if (isnan(mx)) {
            printf("null");
        } else {
            printf("%.0f", mx);
        }
        printf(", \"target_rpm\": ");
        if (isnan(tg)) {
            printf("null");
        } else {
            printf("%.0f", tg);
        }
        printf(", \"mode\": ");
        if (isnan(md)) {
            printf("null");
        } else {
            printf("%.0f", md);
        }
        printf("}%s\n", (i + 1 < fans) ? "," : "");
    }
    printf("  ]\n");
    printf("}\n");
}

static int restore_all_auto(void) {
    int fans = fan_count();
    int ok = 0;
    for (int i = 0; i < fans; i++) {
        if (set_fan_auto(i) == 0) {
            ok++;
        }
    }
    return ok == fans ? 0 : -1;
}

static void on_signal(int sig) {
    (void)sig;
    g_stop = 1;
}

/* Minimal state JSON reader — only fields we need. */
static int json_find_number(const char *json, const char *key, double *out) {
    char pat[64];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p) {
        return -1;
    }
    p = strchr(p + strlen(pat), ':');
    if (!p) {
        return -1;
    }
    p++;
    while (*p == ' ' || *p == '\t') {
        p++;
    }
    char *end = NULL;
    double v = strtod(p, &end);
    if (end == p) {
        return -1;
    }
    *out = v;
    return 0;
}

static int json_get_bool(const char *json, const char *key, int *out) {
    char pat[64];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p) {
        return -1;
    }
    p = strchr(p + strlen(pat), ':');
    if (!p) {
        return -1;
    }
    p++;
    while (*p == ' ' || *p == '\t') {
        p++;
    }
    if (strncmp(p, "true", 4) == 0) {
        *out = 1;
        return 0;
    }
    if (strncmp(p, "false", 5) == 0) {
        *out = 0;
        return 0;
    }
    return -1;
}

typedef struct {
    double temp_c;
    double duty_pct;
} CurvePt;

static int load_state(const char *path, int *stop, int *active, double *emergency_c, CurvePt *pts,
                      int *npt, int max_pts) {
    FILE *f = fopen(path, "r");
    if (!f) {
        return -1;
    }
    char buf[8192];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = '\0';

    *stop = 0;
    *active = 0;
    *emergency_c = 95.0;
    *npt = 0;
    json_get_bool(buf, "stop", stop);
    json_get_bool(buf, "active", active);
    double em = 95.0;
    if (json_find_number(buf, "emergency_c", &em) == 0) {
        *emergency_c = em;
    }

    const char *points = strstr(buf, "\"points\"");
    if (!points) {
        return 0;
    }
    points = strchr(points, '[');
    if (!points) {
        return 0;
    }
    points++;
    while (*points && *npt < max_pts) {
        const char *obj = strchr(points, '{');
        if (!obj) {
            break;
        }
        const char *end = strchr(obj, '}');
        if (!end) {
            break;
        }
        char piece[256];
        size_t len = (size_t)(end - obj + 1);
        if (len >= sizeof(piece)) {
            len = sizeof(piece) - 1;
        }
        memcpy(piece, obj, len);
        piece[len] = '\0';

        double tv = 0, dv = 0;
        if (json_find_number(piece, "temp_c", &tv) == 0 && json_find_number(piece, "duty_pct", &dv) == 0) {
            pts[*npt].temp_c = tv;
            pts[*npt].duty_pct = dv;
            (*npt)++;
        }
        points = end + 1;
        if (*points == ']') {
            break;
        }
    }
    return 0;
}

static double interp_duty(const CurvePt *pts, int n, double temp) {
    if (n <= 0) {
        return 35.0;
    }
    if (temp <= pts[0].temp_c) {
        return pts[0].duty_pct;
    }
    if (temp >= pts[n - 1].temp_c) {
        return pts[n - 1].duty_pct;
    }
    for (int i = 0; i < n - 1; i++) {
        if (temp >= pts[i].temp_c && temp <= pts[i + 1].temp_c) {
            double span = pts[i + 1].temp_c - pts[i].temp_c;
            if (span < 0.001) {
                return pts[i + 1].duty_pct;
            }
            double u = (temp - pts[i].temp_c) / span;
            return pts[i].duty_pct + u * (pts[i + 1].duty_pct - pts[i].duty_pct);
        }
    }
    return pts[n - 1].duty_pct;
}

static int cmp_pts(const void *a, const void *b) {
    const CurvePt *pa = a, *pb = b;
    if (pa->temp_c < pb->temp_c) {
        return -1;
    }
    if (pa->temp_c > pb->temp_c) {
        return 1;
    }
    return 0;
}

static int run_daemon(const char *state_path) {
    if (geteuid() != 0) {
        fprintf(stderr, "{\"error\":\"daemon requires root\"}\n");
        return 2;
    }
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGHUP, SIG_IGN);

    float last_rpm[8];
    for (int i = 0; i < 8; i++) {
        last_rpm[i] = -1;
    }
    int was_active = 0;
    fprintf(stderr, "{\"event\":\"daemon_start\",\"pid\":%d}\n", (int)getpid());
    fflush(stderr);

    while (!g_stop) {
        int stop = 0, active = 0, npt = 0;
        double emergency = 95.0;
        CurvePt pts[16];
        if (load_state(state_path, &stop, &active, &emergency, pts, &npt, 16) != 0) {
            sleep(1);
            continue;
        }
        /* stop=true → exit process (app quit). active=false → Auto, stay alive. */
        if (stop) {
            break;
        }
        if (!active || npt < 2) {
            if (was_active) {
                restore_all_auto();
                was_active = 0;
                for (int i = 0; i < 8; i++) {
                    last_rpm[i] = -1;
                }
                fprintf(stderr, "{\"event\":\"paused_auto\"}\n");
                fflush(stderr);
            }
            sleep(1);
            continue;
        }
        was_active = 1;
        qsort(pts, (size_t)npt, sizeof(CurvePt), cmp_pts);

        float hot = hottest_tracked();
        if (isnan(hot) || hot < -50) {
            int fans = fan_count();
            for (int i = 0; i < fans; i++) {
                char k_mx[8];
                fan_key(k_mx, sizeof(k_mx), i, "Mx");
                float mx = 6000;
                read_float_key(k_mx, &mx);
                set_fan_manual(i, mx);
            }
            sleep(1);
            continue;
        }

        double duty = interp_duty(pts, npt, hot);
        if (hot >= emergency) {
            duty = 100.0;
        }
        if (duty < 0) {
            duty = 0;
        }
        if (duty > 100) {
            duty = 100;
        }

        int fans = fan_count();
        for (int i = 0; i < fans; i++) {
            char k_mn[8], k_mx[8];
            fan_key(k_mn, sizeof(k_mn), i, "Mn");
            fan_key(k_mx, sizeof(k_mx), i, "Mx");
            float mn = 1000, mx = 6000;
            read_float_key(k_mn, &mn);
            read_float_key(k_mx, &mx);
            float target = mn + (float)((duty / 100.0) * (mx - mn));
            if (last_rpm[i] >= 0) {
                float d = target - last_rpm[i];
                if (d > 800) {
                    target = last_rpm[i] + 800;
                }
                if (d < -800) {
                    target = last_rpm[i] - 800;
                }
            }
            set_fan_manual(i, target);
            last_rpm[i] = target;
        }
        sleep(1);
    }

    restore_all_auto();
    fprintf(stderr, "{\"event\":\"daemon_exit\",\"restored\":\"auto\"}\n");
    fflush(stderr);
    return 0;
}

/* Double-fork so process survives the elevated launcher shell exiting. */
static int spawn_daemon(const char *state_path, const char *log_path) {
    int fds[2];
    if (pipe(fds) != 0) {
        return 1;
    }
    pid_t pid = fork();
    if (pid < 0) {
        return 1;
    }
    if (pid > 0) {
        /* Original process: print grandchild pid for the GUI, then exit. */
        close(fds[1]);
        char buf[32];
        memset(buf, 0, sizeof(buf));
        ssize_t n = read(fds[0], buf, sizeof(buf) - 1);
        close(fds[0]);
        if (n > 0) {
            printf("%s\n", buf);
            fflush(stdout);
            return 0;
        }
        fprintf(stderr, "{\"error\":\"daemonize failed\"}\n");
        return 1;
    }

    /* First child */
    close(fds[0]);
    if (setsid() < 0) {
        _exit(1);
    }
    pid = fork();
    if (pid < 0) {
        _exit(1);
    }
    if (pid > 0) {
        /* Report grandchild pid, then exit */
        char buf[32];
        snprintf(buf, sizeof(buf), "%d", (int)pid);
        write(fds[1], buf, strlen(buf));
        close(fds[1]);
        _exit(0);
    }

    /* Grandchild — real daemon */
    close(fds[1]);
    if (log_path && log_path[0]) {
        freopen(log_path, "w", stdout);
        freopen(log_path, "a", stderr);
    }
    /* World-readable pid file so the GUI can find us without signaling root. */
    {
        FILE *pf = fopen("/tmp/smc_thermal_daemon.pid", "w");
        if (pf) {
            fprintf(pf, "%d\n", (int)getpid());
            fclose(pf);
            chmod("/tmp/smc_thermal_daemon.pid", 0644);
        }
    }
    if (smc_open() != 0) {
        fprintf(stderr, "{\"error\":\"AppleSMC open failed\"}\n");
        _exit(1);
    }
    int rc = run_daemon(state_path);
    smc_close();
    _exit(rc);
}

static void usage(void) {
    fprintf(stderr,
            "Usage:\n"
            "  smc_thermal status\n"
            "  smc_thermal auto\n"
            "  smc_thermal set <fan_index> <rpm>\n"
            "  smc_thermal daemon --state <path> [--log <path>]\n");
}

int main(int argc, char **argv) {
    if (!is_apple_silicon()) {
        fprintf(stderr, "{\"error\":\"Apple Silicon only\"}\n");
        return 3;
    }
    if (smc_open() != 0) {
        fprintf(stderr, "{\"error\":\"AppleSMC open failed\"}\n");
        return 1;
    }

    const char *cmd = (argc >= 2) ? argv[1] : "status";
    int rc = 0;

    if (strcmp(cmd, "status") == 0) {
        print_status_json();
    } else if (strcmp(cmd, "auto") == 0) {
        if (geteuid() != 0) {
            fprintf(stderr, "{\"error\":\"auto requires root\"}\n");
            rc = 2;
        } else {
            rc = restore_all_auto() == 0 ? 0 : 1;
            printf("{\"ok\":%s}\n", rc == 0 ? "true" : "false");
        }
    } else if (strcmp(cmd, "set") == 0) {
        if (argc < 4) {
            usage();
            rc = 1;
        } else if (geteuid() != 0) {
            fprintf(stderr, "{\"error\":\"set requires root\"}\n");
            rc = 2;
        } else {
            int idx = atoi(argv[2]);
            float rpm = (float)atof(argv[3]);
            rc = set_fan_manual(idx, rpm) == 0 ? 0 : 1;
            printf("{\"ok\":%s,\"fan\":%d,\"rpm\":%.0f}\n", rc == 0 ? "true" : "false", idx, rpm);
        }
    } else if (strcmp(cmd, "daemon") == 0) {
        const char *path = NULL;
        const char *log_path = "/tmp/smc_thermal_daemon.log";
        for (int i = 2; i < argc; i++) {
            if (strcmp(argv[i], "--state") == 0 && i + 1 < argc) {
                path = argv[++i];
            } else if (strcmp(argv[i], "--log") == 0 && i + 1 < argc) {
                log_path = argv[++i];
            }
        }
        if (!path) {
            usage();
            rc = 1;
        } else if (geteuid() != 0) {
            fprintf(stderr, "{\"error\":\"daemon requires root\"}\n");
            rc = 2;
        } else {
            /* Close SMC in parent before fork; grandchild reopens. */
            smc_close();
            rc = spawn_daemon(path, log_path);
            return rc;
        }
    } else {
        usage();
        rc = 1;
    }

    smc_close();
    return rc;
}
