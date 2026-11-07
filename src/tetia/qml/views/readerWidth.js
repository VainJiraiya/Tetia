// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

.pragma library

// The widths a page is drawn at (the same list as WIDTH_STEPS in models/reader.py; a test keeps them equal).
// A picture is asked for the next step up from the width it is shown at, in real screen pixels, so zooming or
// resizing only loads a new picture when a step is crossed, not for every pixel of difference.
var steps = [600, 800, 1000, 1200, 1600, 2000, 2400, 3000, 3600, 4400]

function forPixels(pixels) {
    for (var i = 0; i < steps.length; i++) {
        if (pixels <= steps[i]) return steps[i]
    }
    return steps[steps.length - 1]
}
