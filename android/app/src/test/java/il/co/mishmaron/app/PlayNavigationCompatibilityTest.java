package il.co.mishmaron.app;

import android.content.Intent;
import android.net.Uri;
import android.os.Looper;
import org.junit.After;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.Config;
import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34)
public class PlayNavigationCompatibilityTest {
    ActivityController<OfflineActivity> controller;
    public static class OfflineActivity extends MainActivity {
        @Override void updateRegistry() { /* Keep regression tests offline. */ }
    }
    void remember(String code, String url) {
        RuntimeEnvironment.getApplication().getSharedPreferences("mishmaron", 0).edit()
            .clear().putString("organization", code).putString("organizationUrl", url).commit();
    }
    OfflineActivity launch(Intent intent) {
        controller = Robolectric.buildActivity(OfflineActivity.class, intent).setup();
        shadowOf(Looper.getMainLooper()).idle();
        return controller.get();
    }
    @After public void destroy() { if (controller != null) controller.pause().stop().destroy(); }
    @Test public void savedPlatformSessionKeepsOriginalHome() {
        remember("platform", MainActivity.PLATFORM);
        OfflineActivity activity = launch(new Intent());
        assertEquals("platform", activity.selected.code);
        assertEquals(MainActivity.PLATFORM, activity.web.getUrl());
        assertNotNull(activity.organizations.get("004"));
    }
    @Test public void existingZibaldSessionKeepsOrganizationAndHomeScreen() {
        String url = "https://employee-time-tracker-production-0910.up.railway.app/";
        remember("004", url);
        OfflineActivity activity = launch(new Intent());
        assertEquals("004", activity.selected.code);
        assertEquals(url + "?app_home=1", activity.web.getUrl());
        assertEquals("004", activity.prefs.getString("organization", ""));
    }
    @Test public void registeredOrganizationDeepLinkStillOpensOriginalRoute() {
        remember("platform", MainActivity.PLATFORM);
        String id = "12345678-1234-1234-1234-123456789abc";
        OfflineActivity activity = launch(new Intent(Intent.ACTION_VIEW, Uri.parse("mishmaron://org/" + id)));
        assertEquals(MainActivity.PLATFORM + "o/" + id + "/", activity.web.getUrl());
    }
    @Test public void untrustedDeepLinkDoesNotOverrideSavedOrganization() {
        remember("platform", MainActivity.PLATFORM);
        OfflineActivity activity = launch(new Intent(Intent.ACTION_VIEW, Uri.parse("mishmaron://evil/org/12345678-1234-1234-1234-123456789abc")));
        assertEquals(MainActivity.PLATFORM, activity.web.getUrl());
    }
}
