import Foundation

struct NavigationPolicy {
    static let platform = URL(string: "https://mishmaron-platform-production.up.railway.app/")!
    let hosts: Set<String>
    init() {
        struct Registry: Decodable { let organizations: [Organization] }
        struct Organization: Decodable { let url: URL }
        let data = Bundle.main.url(forResource: "organizations", withExtension: "json")
            .flatMap { try? Data(contentsOf: $0) }
        let registry = data.flatMap { try? JSONDecoder().decode(Registry.self, from: $0) }
        hosts = Set((registry?.organizations.compactMap { $0.url.host } ?? []) + [Self.platform.host!])
    }
    init(hosts: Set<String>) { self.hosts = hosts.union([Self.platform.host!]) }
    func allows(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && url.user == nil && url.password == nil &&
        (url.port == nil || url.port == 443) && hosts.contains(url.host?.lowercased() ?? "")
    }
    func deepLink(_ url: URL) -> URL? {
        guard url.scheme == "mishmaron", url.host == "org", url.user == nil, url.password == nil,
              url.port == nil, url.query == nil, url.fragment == nil else { return nil }
        let parts = url.path.split(separator: "/")
        guard parts.count == 1, let id = UUID(uuidString: String(parts[0])) else { return nil }
        return Self.platform.appendingPathComponent("o").appendingPathComponent(id.uuidString.lowercased())
    }
    func home(for url: URL) -> URL? {
        guard allows(url) else { return nil }
        if url.host == Self.platform.host {
            let parts = url.path.split(separator: "/")
            if parts.count >= 2, parts[0] == "o", let id = UUID(uuidString: String(parts[1])) {
                return Self.platform.appendingPathComponent("o").appendingPathComponent(id.uuidString.lowercased())
            }
            return Self.platform
        }
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        components.path = "/"; components.query = nil; components.fragment = nil
        return components.url
    }
}
