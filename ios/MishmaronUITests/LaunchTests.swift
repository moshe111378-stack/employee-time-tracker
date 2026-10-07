import XCTest
final class LaunchTests: XCTestCase {
    func testLaunchAndMenu() {
        let app = XCUIApplication(); app.launch()
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 15))
        // Network errors are legitimate offline behavior, dismiss only that known alert.
        if app.alerts["אין חיבור"].waitForExistence(timeout: 3) { app.alerts.buttons["סגירה"].tap() }
        app.buttons["appMenu"].tap()
        XCTAssertTrue(app.buttons["החלפת ארגון"].waitForExistence(timeout: 5))
        app.buttons["ביטול"].tap()
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.lifetime = .keepAlways; add(screenshot)
    }
}
