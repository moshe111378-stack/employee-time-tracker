package il.co.mishmaron.app;

import java.net.URI;
import java.util.Locale;

/** Central URL boundary. Organization origins are supplied only by our registry. */
public final class UrlPolicy {
    private UrlPolicy() {}
    public static String origin(String value) {
        try {
            URI u = new URI(value);
            String host = u.getHost();
            if (!"https".equalsIgnoreCase(u.getScheme()) || host == null || u.getRawUserInfo() != null
                    || (u.getPort() != -1 && u.getPort() != 443) || host.indexOf('.') < 0
                    || host.matches("[0-9.]+") || host.contains(":")) return null;
            return "https://" + host.toLowerCase(Locale.ROOT);
        } catch (Exception e) { return null; }
    }
    public static boolean sameOrigin(String selected, String target) {
        String a = origin(selected), b = origin(target);
        return a != null && a.equals(b);
    }
    public static boolean organizationRoot(String value) {
        try {
            URI u = new URI(value);
            return origin(value) != null && (u.getPath().isEmpty() || "/".equals(u.getPath()))
                    && u.getRawQuery() == null && u.getRawFragment() == null;
        } catch (Exception e) { return false; }
    }
}
