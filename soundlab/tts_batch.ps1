# Speaks a batch of phrases into WAV files with Windows voices (System.Speech).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tts_batch.ps1 jobs.json
# jobs.json: [{"text": "ля", "voice": "Microsoft Irina Desktop", "path": "C:\\...\\x.wav", "rate": -2}]
param([string]$jobs)
Add-Type -AssemblyName System.Speech
$list = Get-Content -Raw -Encoding UTF8 $jobs | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($j in $list) {
  $s.SelectVoice($j.voice)
  $s.Rate = [int]$j.rate
  $s.SetOutputToWaveFile($j.path, $fmt)
  $s.Speak([string]$j.text)
  $s.SetOutputToNull()
}
$s.Dispose()
