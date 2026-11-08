Name:           tetia
Version:        0.4.0
Release:        1%{?dist}
Summary:        A media library for manga, images and video

License:        GPL-3.0-or-later
URL:            https://github.com/VainJiraiya/Tetia
Source0:        %{url}/archive/v%{version}/Tetia-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
BuildRequires:  appstream

# What pip cannot give (see the README): the interface and the icons
Requires:       kf6-kirigami
Requires:       kf6-qqc2-desktop-style
Requires:       breeze-icon-theme
# Played videos, video thumbnails and video covers; Tetia works without them
Recommends:     mpv-libs
Recommends:     ffmpegthumbnailer
Recommends:     ffmpeg

%description
Tetia keeps your manga, pictures and videos in one place on KDE Plasma: browse
collections, tag and rate what is in them, and find anything with one search box.
It has a page reader for comics, PDFs and picture EPUBs, a video player built on
libmpv, and pages for TV shows with the episodes by season.

%prep
%autosetup -n Tetia-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files tetia
install -Dm644 data/io.github.VainJiraiya.Tetia.desktop \
    %{buildroot}%{_datadir}/applications/io.github.VainJiraiya.Tetia.desktop
install -Dm644 data/icons/hicolor/scalable/apps/io.github.VainJiraiya.Tetia.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.VainJiraiya.Tetia.svg
install -Dm644 data/io.github.VainJiraiya.Tetia.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.VainJiraiya.Tetia.metainfo.xml

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.VainJiraiya.Tetia.desktop
appstreamcli validate --no-net %{buildroot}%{_metainfodir}/io.github.VainJiraiya.Tetia.metainfo.xml
%pyproject_check_import

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/tetia
%{_datadir}/applications/io.github.VainJiraiya.Tetia.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.VainJiraiya.Tetia.svg
%{_metainfodir}/io.github.VainJiraiya.Tetia.metainfo.xml

%changelog
* Sun Nov 08 2026 Tetia contributors <noreply@github.com> - 0.4.0-1
- Home tab, boards, pages laid out in rows with pictures in their own shape, booru-like search, series formats

* Sat Nov 07 2026 Tetia contributors <noreply@github.com> - 0.3.2-1
- Open folders at once and scan them in the background; vault lock, thumbnail, reader, player and purge fixes

* Sat Nov 07 2026 Tetia contributors <noreply@github.com> - 0.3.1-1
- Restart into a private profile through the same launcher Tetia was started with

* Fri Nov 06 2026 Tetia contributors <noreply@github.com> - 0.3.0-1
- Video player, shows, playback progress, page reader, virtual folders and tag browser
