import AppKit
import SwiftUI

@main
struct PlaytomicMonitorApp: App {
    @StateObject private var monitor = MonitorController()

    var body: some Scene {
        WindowGroup("Playtomic Monitor") {
            ContentView(monitor: monitor)
                .frame(minWidth: 560, minHeight: 500)
        }
        .defaultSize(width: 660, height: 580)
    }
}

@MainActor
final class MonitorController: ObservableObject {
    @Published var isMonitoring = false
    @Published var isChecking = false
    @Published var lastCheck: Date?
    @Published var lastResult = "No checks have run yet."
    @Published var output = ""
    @Published var projectDirectory: URL?
    @Published var configName = ""

    private var loopTask: Task<Void, Never>?
    private var process: Process?
    private var stopRequested = false

    init() {
        if let savedPath = UserDefaults.standard.string(forKey: "projectDirectory") {
            projectDirectory = URL(fileURLWithPath: savedPath, isDirectory: true)
        } else {
            projectDirectory = Self.findProjectDirectory()
        }
        refreshConfigName()
    }

    var canRun: Bool {
        projectDirectory?.appendingPathComponent("playtomic_monitor.py").isFile == true
            && selectedConfigURL?.isFile == true
    }

    var selectedConfigURL: URL? {
        guard let projectDirectory else { return nil }
        let runtime = projectDirectory.appendingPathComponent("config.runtime.toml")
        let shared = projectDirectory.appendingPathComponent("config.shared.toml")
        if runtime.isFile { return runtime }
        if shared.isFile { return shared }
        return nil
    }

    var intervalSeconds: Int {
        guard let configURL = selectedConfigURL,
              let text = try? String(contentsOf: configURL, encoding: .utf8),
              let range = text.range(of: #"(?m)^\s*interval_seconds\s*=\s*(\d+)"#, options: .regularExpression),
              let value = Int(text[range].split(separator: "=").last?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "") else {
            return 1_200
        }
        return max(value, 60)
    }

    var intervalDescription: String {
        let minutes = intervalSeconds / 60
        return minutes == 1 ? "every minute" : "every \(minutes) minutes"
    }

    func chooseProjectDirectory() {
        let panel = NSOpenPanel()
        panel.title = "Choose the Playtomic monitor folder"
        panel.message = "Select the folder containing playtomic_monitor.py and its config file."
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            projectDirectory = url
            UserDefaults.standard.set(url.path, forKey: "projectDirectory")
            refreshConfigName()
            append("Using folder: \(url.path)")
        }
    }

    func start() {
        guard !isMonitoring, canRun else { return }
        isMonitoring = true
        stopRequested = false
        append("Monitoring started; checking now and then \(intervalDescription).")
        runCheck()
        loopTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                do {
                    try await Task.sleep(nanoseconds: UInt64(self.intervalSeconds) * 1_000_000_000)
                } catch {
                    return
                }
                if Task.isCancelled { return }
                self.runCheck()
            }
        }
    }

    func stop() {
        isMonitoring = false
        stopRequested = true
        loopTask?.cancel()
        loopTask = nil
        if isChecking { process?.terminate() }
        append("Monitoring stopped.")
    }

    func runNow() {
        guard canRun else { return }
        guard !isChecking else {
            append("A check is already running.")
            return
        }
        stopRequested = false
        runCheck()
    }

    private func runCheck() {
        guard !isChecking, let projectDirectory, let configURL = selectedConfigURL else { return }

        let process = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", "playtomic_monitor.py", "--config", configURL.path]
        process.currentDirectoryURL = projectDirectory
        process.environment = [
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": FileManager.default.homeDirectoryForCurrentUser.path,
        ]
        process.standardOutput = stdout
        process.standardError = stderr

        isChecking = true
        lastResult = "Check in progress…"
        output = ""
        self.process = process
        append("Starting local check.")

        let outputQueue = DispatchQueue(label: "playtomic.monitor.output")
        for pipe in [stdout, stderr] {
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else {
                    handle.readabilityHandler = nil
                    return
                }
                guard let text = String(data: data, encoding: .utf8) else { return }
                Task { @MainActor in self?.appendOutput(text) }
            }
        }
        process.terminationHandler = { [weak self] finished in
            outputQueue.async {
                stdout.fileHandleForReading.readabilityHandler = nil
                stderr.fileHandleForReading.readabilityHandler = nil
            }
            Task { @MainActor in
                guard let self else { return }
                self.isChecking = false
                self.process = nil
                self.lastCheck = Date()
                if self.stopRequested {
                    self.lastResult = "Check stopped."
                } else if finished.terminationStatus == 0 {
                    self.lastResult = "Check completed successfully."
                } else {
                    self.lastResult = "Check failed (exit code \(finished.terminationStatus)). See output below."
                }
                self.append(self.lastResult)
            }
        }

        do {
            try process.run()
        } catch {
            isChecking = false
            self.process = nil
            lastCheck = Date()
            lastResult = "Could not start check: \(error.localizedDescription)"
            append(lastResult)
        }
    }

    private func refreshConfigName() {
        configName = selectedConfigURL?.lastPathComponent ?? "No config file found"
    }

    private func append(_ line: String) {
        appendOutput("[\(Date.now.formatted(date: .omitted, time: .shortened))] \(line)\n")
    }

    private func appendOutput(_ text: String) {
        output.append(text)
        if output.count > 24_000 {
            output = String(output.suffix(20_000))
        }
    }

    private static func findProjectDirectory() -> URL? {
        var candidate = Bundle.main.bundleURL.deletingLastPathComponent()
        for _ in 0..<8 {
            if candidate.appendingPathComponent("playtomic_monitor.py").isFile { return candidate }
            candidate.deleteLastPathComponent()
        }
        return nil
    }
}

struct ContentView: View {
    @ObservedObject var monitor: MonitorController

    private static let racketBallArtwork: NSImage? = {
        guard let url = Bundle.main.url(forResource: "PadelRacketBall", withExtension: "png") else { return nil }
        return NSImage(contentsOf: url)
    }()

    private var hasFailure: Bool {
        monitor.lastResult.localizedCaseInsensitiveContains("failed")
            || monitor.lastResult.localizedCaseInsensitiveContains("could not start")
    }

    private var statusText: String {
        if monitor.isChecking { return "Check in progress" }
        if hasFailure { return monitor.isMonitoring ? "Monitoring on · last check failed" : "Last check failed" }
        if monitor.isMonitoring { return "Monitoring is on" }
        return "Monitoring is stopped"
    }

    private var statusColor: Color {
        if monitor.isChecking { return .orange }
        if hasFailure { return .red }
        return monitor.isMonitoring ? .green : .secondary
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 12) {
                Group {
                    if let racketBallArtwork = Self.racketBallArtwork {
                        Image(nsImage: racketBallArtwork)
                            .resizable()
                            .scaledToFill()
                    } else {
                        Image(systemName: "tennisball.fill")
                            .resizable()
                            .scaledToFit()
                            .padding(8)
                            .foregroundStyle(.green)
                    }
                }
                .frame(width: 44, height: 44)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                VStack(alignment: .leading, spacing: 4) {
                    Text("Playtomic Monitor").font(.title2.bold())
                    Label(statusText, systemImage: "circle.fill")
                        .font(.subheadline)
                        .foregroundStyle(statusColor)
                }
                Spacer()
                if monitor.isMonitoring {
                    Button("Stop", role: .destructive) { monitor.stop() }
                        .controlSize(.large)
                } else {
                    Button("Start") { monitor.start() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .disabled(!monitor.canRun)
                }
            }

            HStack(spacing: 12) {
                Button("Run Check Now", systemImage: "play.fill") { monitor.runNow() }
                    .disabled(!monitor.canRun || monitor.isChecking)
                Text(monitor.isMonitoring ? "Automatic checks \(monitor.intervalDescription)." : "Start monitoring to check on a schedule.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            GroupBox("Local setup") {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Folder")
                            .foregroundStyle(.secondary)
                        Text(monitor.projectDirectory?.path ?? "Not selected")
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Button("Choose…") { monitor.chooseProjectDirectory() }
                    }
                    HStack {
                        Text("Config")
                            .foregroundStyle(.secondary)
                        Text(monitor.configName)
                        Spacer()
                        Text("Checks run while this app is open")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.callout)
                .padding(.top, 4)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Latest result").font(.headline)
                Text(monitor.lastResult)
                Text(monitor.lastCheck.map { "Last check: \($0.formatted(date: .abbreviated, time: .shortened))" } ?? "Last check: —")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Activity").font(.headline)
                ScrollView {
                    Text(monitor.output.isEmpty ? "Output from the local script will appear here." : monitor.output)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .padding(10)
                }
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                .frame(minHeight: 150)
            }

            if !monitor.canRun {
                Label("Choose the project folder containing the script and a config file.", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
        .padding(24)
    }
}

private extension URL {
    var isFile: Bool { FileManager.default.fileExists(atPath: path) }
}
