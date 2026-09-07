/*
	SlimeVR Code is placed under the MIT license
	Copyright (c) 2025 Gorbit99 & SlimeVR Contributors

	Permission is hereby granted, free of charge, to any person obtaining a copy
	of this software and associated documentation files (the "Software"), to deal
	in the Software without restriction, including without limitation the rights
	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the Software is
	furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in
	all copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
	THE SOFTWARE.
*/

#include "SensorInterfaceManager.h"

template <typename T>
bool byteCompare(const T& lhs, const T& rhs) {
	const auto* lhsBytes = reinterpret_cast<const uint8_t*>(&lhs);
	const auto* rhsBytes = reinterpret_cast<const uint8_t*>(&rhs);

	// Lexicographic. This returned true on the first byte where lhs was smaller but
	// continued when it was larger, so for a = {5, 0} and b = {3, 9} both
	// byteCompare(a, b) and byteCompare(b, a) were true. That is not a strict weak
	// ordering, and std::map keyed on such a comparator has undefined behaviour: a
	// lookup that should hit can miss and construct a duplicate interface, calling
	// begin() on a bus that is already up.
	for (size_t i = 0; i < sizeof(T); i++) {
		if (lhsBytes[i] != rhsBytes[i]) {
			return lhsBytes[i] < rhsBytes[i];
		}
	}

	return false;
}

bool operator<(const SPISettings& lhs, const SPISettings& rhs) {
	return byteCompare(lhs, rhs);
}

bool operator<(const SPIClass& lhs, const SPIClass& rhs) {
	return byteCompare(lhs, rhs);
}
