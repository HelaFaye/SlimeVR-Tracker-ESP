// Routes firmware logging to stdout, indented, so scenario output stays readable.
#include <cstdarg>
#include <cstdio>

#include "logging/Logger.h"

namespace SlimeVR::Logging {
static void emit(const char* level, const char* fmt, va_list args) {
	std::printf("     %s ", level);
	std::vprintf(fmt, args);
	std::printf("\n");
}
#define IMPL(name, tag)                          \
	void Logger::name(const char* fmt, ...) const { \
		va_list a;                               \
		va_start(a, fmt);                        \
		emit(tag, fmt, a);                       \
		va_end(a);                               \
	}
IMPL(trace, "trace")
IMPL(debug, "debug")
IMPL(info, "info ")
IMPL(warn, "WARN ")
IMPL(error, "ERROR")
IMPL(fatal, "FATAL")
#undef IMPL
void Logger::setTag(const char*) {}
void Logger::log(Level, const char*, va_list) const {}
void Logger::tick() {}
const char* levelToString(Level) { return ""; }
}  // namespace SlimeVR::Logging
