import XCTest
final class LaunchTests: XCTestCase {
    func testHomeWorkerNavigationAndMenu() {
        let app = XCUIApplication(); app.launch()
        let web = app.webViews.firstMatch
        XCTAssertTrue(web.waitForExistence(timeout: 15))
        let worker = web.buttons["ממשק עובדים"]
        XCTAssertTrue(worker.waitForExistence(timeout: 45), "The real organization home must load; an empty WebView is not success")
        XCTAssertTrue(web.links["ממשק מנהלים"].exists)
        saveScreenshot(app, name: "01-home")
        worker.tap()
        XCTAssertTrue(web.staticTexts["דיווח נוכחות"].waitForExistence(timeout: 10))
        saveScreenshot(app, name: "02-worker")
        web.buttons["חזרה למסך הראשי"].tap()
        XCTAssertTrue(worker.waitForExistence(timeout: 10))
        app.buttons["appMenu"].tap()
        XCTAssertTrue(app.buttons["החלפת ארגון"].waitForExistence(timeout: 5))
        app.buttons["ביטול"].tap()
        web.links["ממשק מנהלים"].tap()
        XCTAssertTrue(web.secureTextFields.firstMatch.waitForExistence(timeout: 20))
        saveScreenshot(app, name: "03-manager-login")
    }
    private func saveScreenshot(_ app: XCUIApplication, name: String) {
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name; screenshot.lifetime = .keepAlways; add(screenshot)
    }
}
