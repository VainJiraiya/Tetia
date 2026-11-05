// SPDX-FileCopyrightText: 2026 Tetia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

.pragma library

// A file's path as a fully percent-encoded file:// address, for an image://thumbnail/ source.
//
// A bare path does not survive the trip to the image provider: Qt turns "{" and "}" into
// %7B and %7D, and decodes a literal "%20" in a folder name into a space, so the provider
// looks for a file that does not exist. A fully encoded address is unambiguous: the provider
// decodes it exactly once.
function fromPath(path) {
    return "file://" + path.split("/").map(encodeURIComponent).join("/")
}
