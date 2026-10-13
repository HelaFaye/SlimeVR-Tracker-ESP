// Silent logger for the sweep: 14 million configurations would otherwise emit tens of
// millions of enumeration lines, and the sweep asserts rather than reads output.
#include <cstdarg>

#include "logging/Logger.h"
namespace SlimeVR::Logging {
void Logger::trace(const char*, ...) const {}
void Logger::debug(const char*, ...) const {}
void Logger::info(const char*, ...) const {}
void Logger::warn(const char*, ...) const {}
void Logger::error(const char*, ...) const {}
void Logger::fatal(const char*, ...) const {}
void Logger::setTag(const char*) {}
void Logger::log(Level, const char*, va_list) const {}
void Logger::tick() {}
const char* levelToString(Level) { return ""; }
}  // namespace SlimeVR::Logging
