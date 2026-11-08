// trim: cut the three capture webms into the shot-list clips (h264 1080p30, crf 18)
import { execFileSync } from 'node:child_process'

const RAW = 'C:/dev/wt-video/video/capture/raw'
const OUT = 'C:/dev/wt-video/video/clips'
const A = RAW + '/page@29211cbd6ec4045e70424885f81f5bce.webm'
const B = RAW + '/page@71583b0c7015427aae886f9532763c80.webm'
const C = RAW + '/page@c6f7163ac006d5f44656f4c98b7536c3.webm'

// [source, start, end, name] — times are video-relative, from markers.json + review
const cuts = [
  [A, 0.6, 3.2, 'console-alert'],
  [A, 3.0, 8.2, 'console-open-case'],
  [B, 0.7, 5.5, 'case-rail'],
  [B, 5.3, 9.7, 'case-seal'],
  [B, 8.9, 12.0, 'case-steps'],
  [B, 10.6, 14.9, 'case-findings'],
  [B, 11.0, 14.5, 'case-injection'],
  [B, 14.5, 19.6, 'case-dns'],
  [B, 19.0, 26.4, 'approve-flow'],
  [B, 25.8, 34.5, 'close-blast'],
  [C, 0.4, 4.4, 'console-alert-auto'],
  [C, 4.3, 8.9, 'case-auto'],
]

for (const [src, s, e, name] of cuts) {
  const out = `${OUT}/${name}.mp4`
  console.log('trim', name, s, '->', e)
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y',
    '-i', src, '-ss', String(s), '-to', String(e),
    '-vf', 'scale=1920:1080:flags=lanczos,fps=30',
    '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-pix_fmt', 'yuv420p',
    '-an', out])
}
console.log('done:', cuts.length, 'clips')
