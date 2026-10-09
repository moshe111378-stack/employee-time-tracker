import XCTest

final class LaunchTests: XCTestCase {
    func testHomeWorkerNavigationAndMenu() {
        let app = XCUIApplication()
        // Use the repository's explicitly designated test tenant. The platform landing page
        // cannot open worker attendance until an organization-specific link is provided.
        app.launchArguments += [
            "-organizationHome",
            "https://mishmaron-master-time-test-production.up.railway.app/"
        ]
        app.launch()

        let web = app.webViews.firstMatch
        XCTAssertTrue(web.waitForExistence(timeout: 15))

        let worker = web.buttons["כניסת עובדים למערכת"]
        XCTAssertTrue(worker.waitForExistence(timeout: 45), "The test organization home must load")
        XCTAssertTrue(web.links["כניסת מנהלים"].exists)
        saveScreenshot(app, name: "01-home")

        worker.tap()
        XCTAssertTrue(web.staticTexts["דיווח נוכחות"].waitForExistence(timeout: 10))
        let back = web.buttons["חזרה למסך הראשי"]
        XCTAssertTrue(back.waitForExistence(timeout: 10))
        saveScreenshot(app, name: "02-worker")

        back.tap()
        XCTAssertTrue(worker.waitForExistence(timeout: 10))

        app.buttons["appMenu"].tap()
        XCTAssertTrue(app.buttons["החלפת ארגון"].waitForExistence(timeout: 5))
        app.buttons["ביטול"].tap()

        web.links["כניסת מנהלים"].tap()
        XCTAssertTrue(web.secureTextFields.firstMatch.waitForExistence(timeout: 20))
        saveScreenshot(app, name: "03-manager-login")
    }

    private func saveScreenshot(_ app: XCUIApplication, name: String) {
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }
}
