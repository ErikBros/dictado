// ecoscribe-systap: the system audio for meetings on macOS (the WASAPI loopback of the Mac).
//
// A Core Audio process tap (macOS 14.4+) on every process's output except Ecoscribe's own (its
// start/stop tones must not land on the "Others" track), in a private aggregate device clocked by
// the current output device. stdout: one JSON header line {"rate", "channels", "device"}, then raw
// interleaved float32 frames. Exits 0 when stdin closes (Ecoscribe went away), 3 when the default
// output device changes (Ecoscribe starts a new one), 2 on a setup error (message on stderr).
// Needs "Screen & System Audio Recording" (System Audio Recording Only) for the responsible app.
//
// Build: swiftc -O -o ecoscribe-systap systap.swift   (Ecoscribe does it on first use in a dev setup)
// Usage: ecoscribe-systap [<pid to exclude> ...]
import AudioToolbox
import CoreAudio
import Foundation

func fail(_ msg: String, _ status: OSStatus = 0) -> Never {
    FileHandle.standardError.write("ecoscribe-systap: \(msg)\(status != 0 ? " (OSStatus \(status))" : "")\n".data(using: .utf8)!)
    exit(2)
}

func address(_ sel: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal,
                               mElement: kAudioObjectPropertyElementMain)
}

func getID(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector) -> AudioObjectID {
    var addr = address(sel)
    var id = AudioObjectID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    let st = AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &id)
    if st != noErr { fail("property \(sel) unreadable", st) }
    return id
}

func getString(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector) -> String {
    var addr = address(sel)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    let st = AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &value)
    if st != noErr { return "" }
    return value?.takeRetainedValue() as String? ?? ""
}

func processObject(pid: pid_t) -> AudioObjectID? {
    var addr = address(kAudioHardwarePropertyTranslatePIDToProcessObject)
    var p = pid
    var id = AudioObjectID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    let st = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr,
                                        UInt32(MemoryLayout<pid_t>.size), &p, &size, &id)
    return st == noErr && id != kAudioObjectUnknown ? id : nil
}

// Ecoscribe went away (stdin closed): leave, even while setup still waits for consent. Private taps
// and aggregate devices die with the process, so exiting here leaks nothing.
Thread.detachNewThread {
    while FileHandle.standardInput.availableData.count > 0 {}
    exit(0)
}

// ---- the tap -------------------------------------------------------------------------------------
let system = AudioObjectID(kAudioObjectSystemObject)
let output = getID(system, kAudioHardwarePropertyDefaultOutputDevice)
let outputUID = getString(output, kAudioDevicePropertyDeviceUID)
let outputName = getString(output, kAudioObjectPropertyName)
if outputUID.isEmpty { fail("no default output device") }

var exclude: [AudioObjectID] = []
for arg in CommandLine.arguments.dropFirst() {
    if let pid = pid_t(arg), let obj = processObject(pid: pid) { exclude.append(obj) }
}
if let me = processObject(pid: getpid()) { exclude.append(me) }

let desc = CATapDescription(stereoGlobalTapButExcludeProcesses: exclude)
desc.uuid = UUID()
desc.muteBehavior = .unmuted
desc.isPrivate = true
desc.name = "Ecoscribe system audio"

var tap = AudioObjectID(kAudioObjectUnknown)
var st = AudioHardwareCreateProcessTap(desc, &tap)
if st != noErr { fail("process tap not created", st) }

var fmtAddr = address(kAudioTapPropertyFormat)
var fmt = AudioStreamBasicDescription()
var fmtSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
st = AudioObjectGetPropertyData(tap, &fmtAddr, 0, nil, &fmtSize, &fmt)
if st != noErr { fail("tap format unreadable", st) }
if fmt.mFormatID != kAudioFormatLinearPCM || fmt.mFormatFlags & kAudioFormatFlagIsFloat == 0 || fmt.mBitsPerChannel != 32 {
    fail("unexpected tap format \(fmt)")
}

let aggregate: [String: Any] = [
    kAudioAggregateDeviceNameKey: "Ecoscribe system audio",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceMainSubDeviceKey: outputUID,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceIsStackedKey: false,
    kAudioAggregateDeviceTapAutoStartKey: true,
    kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID]],
    kAudioAggregateDeviceTapListKey: [[kAudioSubTapDriftCompensationKey: true,
                                       kAudioSubTapUIDKey: desc.uuid.uuidString]],
]
var agg = AudioObjectID(kAudioObjectUnknown)
st = AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &agg)
if st != noErr { AudioHardwareDestroyProcessTap(tap); fail("aggregate device not created", st) }

var procID: AudioDeviceIOProcID?
func cleanup() {
    if let p = procID { AudioDeviceStop(agg, p); AudioDeviceDestroyIOProcID(agg, p) }
    AudioHardwareDestroyAggregateDevice(agg)
    AudioHardwareDestroyProcessTap(tap)
}

let out = FileHandle.standardOutput
let writer = DispatchQueue(label: "ecoscribe-systap.write")
var started = false  // touched only on `writer`
st = AudioDeviceCreateIOProcIDWithBlock(&procID, agg, writer) { _, input, _, _, _ in
    guard started else { return }
    let list = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
    for buf in list {
        guard let data = buf.mData, buf.mDataByteSize > 0 else { continue }
        do { try out.write(contentsOf: Data(bytes: data, count: Int(buf.mDataByteSize))) } catch { cleanup(); exit(0) }
    }
}
if st != noErr { cleanup(); fail("IO proc not created", st) }
st = AudioDeviceStart(agg, procID)
if st != noErr { cleanup(); fail("device not started", st) }
// The header only now: while macOS waits for the user's consent, IOProc creation above blocks and
// Ecoscribe sees no header (it keeps the mic going and says which permission is missing).
let header: [String: Any] = ["rate": fmt.mSampleRate, "channels": Int(fmt.mChannelsPerFrame), "device": outputName]
writer.sync {
    out.write(try! JSONSerialization.data(withJSONObject: header) + "\n".data(using: .utf8)!)
    started = true
}

// ---- leave when Ecoscribe goes away or the output device changes -----------------------------------
var outAddr = address(kAudioHardwarePropertyDefaultOutputDevice)
AudioObjectAddPropertyListenerBlock(system, &outAddr, DispatchQueue.main) { _, _ in
    if getID(system, kAudioHardwarePropertyDefaultOutputDevice) != output { cleanup(); exit(3) }
}
for sig in [SIGTERM, SIGINT] {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { cleanup(); exit(0) }
    src.resume()
    _ = Unmanaged.passRetained(src)
}
dispatchMain()
