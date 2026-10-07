import XCTest
@testable import Mishmaron
final class NavigationPolicyTests: XCTestCase {
    let policy = NavigationPolicy(hosts: ["mishmaron-nahi.up.railway.app"])
    func testOriginBoundary() {
        XCTAssertTrue(policy.allows(URL(string: "https://mishmaron-nahi.up.railway.app/admin")!))
        for value in ["http://mishmaron-nahi.up.railway.app/", "https://mishmaron-nahi.up.railway.app.evil.example/", "https://mishmaron-nahi.up.railway.app:444/", "https://user@mishmaron-nahi.up.railway.app/", "file:///etc/passwd", "javascript:alert(1)"] {
            XCTAssertFalse(policy.allows(URL(string: value)!), value)
        }
    }
    func testDeepLinksDoNotAcceptArbitraryDestinations() {
        let id = "12345678-1234-1234-1234-123456789abc"
        XCTAssertEqual(policy.deepLink(URL(string: "mishmaron://org/" + id)!)?.absoluteString, NavigationPolicy.platform.absoluteString + "o/" + id)
        for suffix in ["not-a-uuid", id + "/admin", id + "?url=https://evil.example", id + "#admin"] {
            XCTAssertNil(policy.deepLink(URL(string: "mishmaron://org/" + suffix)!))
        }
    }
    func testRememberOnlyOrganizationHome() {
        let root = NavigationPolicy.platform.absoluteString
        let id = "12345678-1234-1234-1234-123456789abc"
        XCTAssertEqual(policy.home(for: URL(string: root + "o/" + id + "/admin?token=secret")!)?.absoluteString, root + "o/" + id)
        XCTAssertEqual(policy.home(for: URL(string: "https://mishmaron-nahi.up.railway.app/event/7?x=1")!)?.absoluteString, "https://mishmaron-nahi.up.railway.app/")
        XCTAssertNil(policy.home(for: URL(string: "https://evil.example/")!))
    }
}
