import UIKit
import WebKit

final class BrowserViewController: UIViewController, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    private let policy = NavigationPolicy()
    private var web: WKWebView!
    private let progress = UIProgressView(progressViewStyle: .bar)
    private var observation: NSKeyValueObservation?
    private var downloadFiles: [ObjectIdentifier: URL] = [:]
    private let navy = UIColor(red: 7/255, green: 21/255, blue: 43/255, alpha: 1)
    private let gold = UIColor(red: 217/255, green: 181/255, blue: 90/255, alpha: 1)
    private var home: URL {
        guard let value = UserDefaults.standard.string(forKey: "organizationHome"),
              let url = URL(string: value), let safe = policy.home(for: url) else { return NavigationPolicy.platform }
        return safe
    }
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = navy
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        config.allowsInlineMediaPlayback = true
        // Reuse the release Android presentation script, changing only the local image transport.
        if let file = Bundle.main.url(forResource: "app-presentation", withExtension: "js"),
           let source = try? String(contentsOf: file, encoding: .utf8),
           let logoURL = Bundle.main.url(forResource: "brand_logo", withExtension: "png"),
           let logo = try? Data(contentsOf: logoURL) {
            let script = source.replacingOccurrences(of: "/__mishmaron_native_brand_v2.png", with: "data:image/png;base64," + logo.base64EncodedString())
            config.userContentController.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        }
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self; web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        web.isOpaque = false; web.backgroundColor = navy
        web.scrollView.backgroundColor = navy
        web.accessibilityIdentifier = "mishmaronWeb"
        let title = UILabel(); title.text = "משמרון"; title.textColor = gold
        title.font = .boldSystemFont(ofSize: 20); title.textAlignment = .right
        let icon = UIImageView(image: UIImage(named: "brand_logo")); icon.contentMode = .scaleAspectFit
        icon.widthAnchor.constraint(equalToConstant: 40).isActive = true
        let menu = UIButton(type: .system); menu.setTitle("תפריט", for: .normal)
        menu.tintColor = gold; menu.accessibilityIdentifier = "appMenu"
        menu.addTarget(self, action: #selector(showMenu), for: .touchUpInside)
        let bar = UIStackView(arrangedSubviews: [menu, title, icon])
        bar.spacing = 12; bar.alignment = .center
        bar.isLayoutMarginsRelativeArrangement = true
        bar.directionalLayoutMargins = NSDirectionalEdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 12)
        bar.heightAnchor.constraint(equalToConstant: 52).isActive = true
        progress.tintColor = gold
        let stack = UIStackView(arrangedSubviews: [bar, progress, web]); stack.axis = .vertical
        stack.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            stack.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            stack.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor)
        ])
        observation = web.observe(\.estimatedProgress, options: [.new]) { [weak self] web, _ in
            self?.progress.progress = Float(web.estimatedProgress)
            self?.progress.isHidden = web.estimatedProgress >= 1
        }
        loadHome()
    }
    private func loadHome() {
        var parts = URLComponents(url: home, resolvingAgainstBaseURL: false)!
        parts.queryItems = [URLQueryItem(name: "app_home", value: "1")]
        web.load(URLRequest(url: parts.url!))
    }
    @discardableResult func openDeepLink(_ url: URL) -> Bool {
        guard let target = policy.deepLink(url) else { return false }
        loadViewIfNeeded()
        UserDefaults.standard.set(target.absoluteString, forKey: "organizationHome")
        loadHome(); return true
    }
    @objc private func showMenu() {
        let sheet = UIAlertController(title: "משמרון", message: nil, preferredStyle: .actionSheet)
        sheet.addAction(UIAlertAction(title: "חזרה", style: .default) { [weak self] _ in self?.web.goBack() })
        sheet.addAction(UIAlertAction(title: "מסך ראשי", style: .default) { [weak self] _ in self?.loadHome() })
        sheet.addAction(UIAlertAction(title: "רענון", style: .default) { [weak self] _ in self?.web.reload() })
        sheet.addAction(UIAlertAction(title: "החלפת ארגון", style: .default) { [weak self] _ in self?.confirmSwitch() })
        sheet.addAction(UIAlertAction(title: "פרטיות ומחיקת מידע", style: .default) { [weak self] _ in
            self?.external(URL(string: "https://mishmaron-privacy-production.up.railway.app/privacy")!)
        })
        sheet.addAction(UIAlertAction(title: "פנייה לתמיכה", style: .default) { [weak self] _ in
            self?.external(URL(string: "mailto:moshe111378@gmail.com")!)
        })
        sheet.addAction(UIAlertAction(title: "ביטול", style: .cancel))
        sheet.popoverPresentationController?.sourceView = view
        sheet.popoverPresentationController?.sourceRect = CGRect(x: 20, y: view.safeAreaInsets.top + 26, width: 1, height: 1)
        present(sheet, animated: true)
    }
    private func confirmSwitch() {
        let alert = UIAlertController(title: "החלפת ארגון", message: "הפעולה תנתק את ההתחברות במכשיר זה. הדיווחים בשרת יישמרו.", preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "ביטול", style: .cancel))
        alert.addAction(UIAlertAction(title: "החלפה", style: .destructive) { [weak self] _ in
            guard let self else { return }
            self.web.stopLoading()
            self.web.loadHTMLString("", baseURL: nil)
            WKWebsiteDataStore.default().removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: .distantPast) { [weak self] in
                UserDefaults.standard.removeObject(forKey: "organizationHome")
                self?.loadHome()
            }
        })
        present(alert, animated: true)
    }
    private func external(_ url: URL) {
        guard ["https", "mailto", "tel"].contains(url.scheme?.lowercased() ?? "") else { return }
        let alert = UIAlertController(title: "פתיחת קישור", message: "לפתוח מחוץ למשמרון?", preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "ביטול", style: .cancel))
        alert.addAction(UIAlertAction(title: "פתיחה", style: .default) { _ in UIApplication.shared.open(url) })
        present(alert, animated: true)
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if policy.deepLink(url) != nil { decisionHandler(.cancel); openDeepLink(url); return }
        guard policy.allows(url) else {
            decisionHandler(.cancel)
            if action.navigationType == .linkActivated { external(url) }
            return
        }
        if action.shouldPerformDownload { decisionHandler(.download); return }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        guard let url = response.response.url, policy.allows(url) else { decisionHandler(.cancel); return }
        let disposition = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? ""
        decisionHandler(!response.canShowMIMEType || disposition.lowercased().contains("attachment") ? .download : .allow)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url, let target = policy.home(for: url) {
            UserDefaults.standard.set(target.absoluteString, forKey: "organizationHome")
        }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { connectionError(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { connectionError(error) }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }
    private func connectionError(_ error: Error) {
        guard (error as NSError).code != NSURLErrorCancelled, presentedViewController == nil else { return }
        let alert = UIAlertController(title: "אין חיבור", message: "לא ניתן לטעון את המערכת. בדקו את חיבור האינטרנט ונסו שוב.", preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "רענון", style: .default) { [weak self] _ in
            guard let self else { return }; if self.web.url == nil { self.loadHome() } else { self.web.reload() }
        })
        alert.addAction(UIAlertAction(title: "סגירה", style: .cancel)); present(alert, animated: true)
    }
    // The attendance code uses prompt() for worker verification; WebKit needs a native handler.
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        guard let url = frame.request.url, policy.allows(url), presentedViewController == nil else { completionHandler(nil); return }
        let alert = UIAlertController(title: "משמרון", message: prompt, preferredStyle: .alert)
        alert.addTextField { field in field.text = defaultText; field.textAlignment = .right; field.isSecureTextEntry = true; field.autocorrectionType = .no }
        alert.addAction(UIAlertAction(title: "ביטול", style: .cancel) { _ in completionHandler(nil) })
        alert.addAction(UIAlertAction(title: "אישור", style: .default) { _ in completionHandler(alert.textFields?.first?.text) })
        present(alert, animated: true)
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        guard presentedViewController == nil else { completionHandler(); return }
        let alert = UIAlertController(title: "משמרון", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "אישור", style: .default) { _ in completionHandler() }); present(alert, animated: true)
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard presentedViewController == nil else { completionHandler(false); return }
        let alert = UIAlertController(title: "משמרון", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "ביטול", style: .cancel) { _ in completionHandler(false) })
        alert.addAction(UIAlertAction(title: "אישור", style: .default) { _ in completionHandler(true) }); present(alert, animated: true)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { if policy.allows(url) { webView.load(action.request) } else { external(url) } }
        return nil
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        guard let url = response.url, policy.allows(url) else { completionHandler(nil); return }
        do {
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let name = URL(fileURLWithPath: suggestedFilename).lastPathComponent
            let file = directory.appendingPathComponent(name.isEmpty ? "mishmaron-report.xls" : name)
            downloadFiles[ObjectIdentifier(download)] = file; completionHandler(file)
        } catch { completionHandler(nil) }
    }
    func download(_ download: WKDownload, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, decisionHandler: @escaping (WKDownload.RedirectPolicy) -> Void) {
        decisionHandler(request.url.map(policy.allows) == true ? .allow : .cancel)
    }
    func downloadDidFinish(_ download: WKDownload) {
        guard let file = downloadFiles.removeValue(forKey: ObjectIdentifier(download)) else { return }
        let sheet = UIActivityViewController(activityItems: [file], applicationActivities: nil)
        sheet.popoverPresentationController?.sourceView = view
        sheet.popoverPresentationController?.sourceRect = CGRect(x: view.bounds.midX, y: view.bounds.midY, width: 1, height: 1)
        sheet.completionWithItemsHandler = { _, _, _, _ in try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        present(sheet, animated: true)
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if let file = downloadFiles.removeValue(forKey: ObjectIdentifier(download)) { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        connectionError(error)
    }
}
