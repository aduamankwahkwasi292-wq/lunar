FFmpeg in MrSOLIS 3
===================

MrSOLIS uses FFmpeg (ffmpeg.exe and ffprobe.exe, with the FFmpeg libraries in this folder) to watch videos
the student attaches: it pulls out the soundtrack for speech recognition and grabs still frames.
MrSOLIS runs these programs as separate processes; it does not change them.

What this is
  FFmpeg n9.0.2-35-g9a9b70bb8c (built 2026-10-24), the "win64-lgpl-shared" build from the BtbN FFmpeg-Builds
  project: https://github.com/BtbN/FFmpeg-Builds  (release "latest",
  file ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip,
  SHA-256 5a204635723d3c28365aec847b79649f340873d8cc4bde632c619187c17992fd). "latest" is replaced daily; the
  same FFmpeg version is pinned in the dated release autobuild-2026-10-24-13-02 as
  ffmpeg-n9.0.2-35-g9a9b70bb8c-win64-lgpl-shared-9.0.zip
  (SHA-256 fb771d872989dba5d96621a840194362202426e882814a0d5e7eddd8387908d3) — use that one for release builds.
  Built without --enable-gpl and without --enable-nonfree ("ffmpeg -buildconf" shows the full configuration).
  ffplay.exe, the headers, import libraries and documentation from that archive are left out.

Licence
  FFmpeg is free software, licensed here under the GNU Lesser General Public License, version 3 or later:
  see LICENSE.txt (LGPL v3) and COPYING.GPLv3.txt (the GNU GPL v3, which the LGPL v3 builds on).
  FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project. MrSOLIS is not affiliated with it.

Source code
  FFmpeg's source for this version: https://github.com/FFmpeg/FFmpeg (tag/branch n9.0, commit 9a9b70bb8c),
  also at https://ffmpeg.org/download.html. The scripts that built these files: https://github.com/BtbN/FFmpeg-Builds.
  You may replace the DLLs and programs in this folder with your own build of FFmpeg.
