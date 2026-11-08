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

// The thumbnail size (a freedesktop cache tier: 128, 256, 512 or 1024 px) to ask for, so that a picture that is
// `pixels` tall or wide on the screen is not stretched. `pixels` are real screen pixels: the size in the window
// times the screen's devicePixelRatio. It rounds up, so it only changes at the tier boundaries.
function tierFor(pixels) {
    return pixels <= 128 ? 128 : pixels <= 256 ? 256 : pixels <= 512 ? 512 : 1024
}

var VIDEO_SUFFIXES = [".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv"]

function isVideo(pathOrUri) {
    var name = String(pathOrUri).toLowerCase()
    for (var i = 0; i < VIDEO_SUFFIXES.length; i++)
        if (name.length > VIDEO_SUFFIXES[i].length && name.slice(-VIDEO_SUFFIXES[i].length) === VIDEO_SUFFIXES[i]) return true
    return false
}

// The image:// source of a file's thumbnail (a path or a file:// address). A video's comes without the film strip
// ffmpegthumbnailer draws on its sides (its width follows the thumbnail's, so it looked different on every tile);
// the provider crops it off and leaves the shared cache as it is.
function source(pathOrUri) {
    if (!pathOrUri) return ""
    var uri = String(pathOrUri).indexOf("file://") === 0 ? String(pathOrUri) : fromPath(String(pathOrUri))
    return "image://thumbnail/" + (isVideo(uri) ? "nostrip/" : "") + uri
}
