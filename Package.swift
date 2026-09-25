// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "PlaytomicMonitorApp",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "PlaytomicMonitorApp", targets: ["PlaytomicMonitorApp"]),
    ],
    targets: [
        .executableTarget(
            name: "PlaytomicMonitorApp",
            exclude: ["Resources"]
        ),
    ]
)
