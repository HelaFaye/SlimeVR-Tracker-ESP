// Silent logger for the sweep: 14 million configurations would otherwise emit tens of
// millions of enumeration lines, and the sweep asserts rather than reads output.
#include <cstdarg>
#include "logging/Logger.h"
namespace SlimeVR::Logging {
#define IMPL(name) void Logger::name(const char*, ...) const {}
IMPL(trace) IMPL(debug) IMPL(info) IMPL(warn) IMPL(error) IMPL(fatal)
#undef IMPL
void Logger::setTag(const char*) {}
void Logger::log(Level, const char*, va_list) const {}
void Logger::tick() {}
const char* levelToString(Level) { return ""; }
}
