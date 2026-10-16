package il.co.mishmaron.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.ActivityNotFoundException;
import android.net.Uri;
import android.os.Looper;
import android.provider.MediaStore;
import android.webkit.ValueCallback;
import android.view.View;
import android.widget.Button;
import androidx.core.content.FileProvider;
import java.io.OutputStream;
import java.util.Map;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowActivity;
import org.robolectric.shadows.ShadowAlertDialog;
import org.robolectric.util.ReflectionHelpers;
import static org.robolectric.Shadows.shadowOf;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34)
public class AttendanceCameraTest {
    Activity activity;
    AttendanceCamera camera;
    static class Result implements ValueCallback<Uri[]> {
        int calls;
        Uri[] value;
        public void onReceiveValue(Uri[] value) { calls++; this.value = value; }
    }
    @Before public void setup() {
        // Robolectric creates a new cache directory for each test in the same JVM.
        // AndroidX otherwise retains a FileProvider root from the previous test.
        Map<?, ?> roots = ReflectionHelpers.getStaticField(FileProvider.class, "sCache");
        roots.clear();
        activity = Robolectric.buildActivity(Activity.class).setup().get();
        camera = new AttendanceCamera(activity);
    }
    ShadowActivity.IntentForResult launch(Result result) {
        camera.choose(result);
        AlertDialog dialog = ShadowAlertDialog.getLatestAlertDialog();
        Button gallery = dialog.getButton(AlertDialog.BUTTON_NEUTRAL);
        assertTrue(gallery == null || gallery.getVisibility() != View.VISIBLE);
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick();
        shadowOf(Looper.getMainLooper()).idle();
        ShadowActivity.IntentForResult launched = shadowOf(activity).getNextStartedActivityForResult();
        assertNotNull(launched);
        assertEquals(MediaStore.ACTION_IMAGE_CAPTURE, launched.intent.getAction());
        return launched;
    }
    Uri output(ShadowActivity.IntentForResult launched) {
        return launched.intent.getParcelableExtra(MediaStore.EXTRA_OUTPUT);
    }
    void writePhoto(Uri uri) throws Exception {
        try (OutputStream stream = activity.getContentResolver().openOutputStream(uri)) {
            stream.write(new byte[]{(byte)0xff, (byte)0xd8, (byte)0xff, (byte)0xd9});
        }
    }
    @Test public void cameraIsTheOnlyChoiceAndSuccessfulOutputIsReturned() throws Exception {
        Result result = new Result();
        ShadowActivity.IntentForResult launched = launch(result);
        Uri uri = output(launched);
        assertEquals("content", uri.getScheme());
        assertEquals(activity.getPackageName() + ".files", uri.getAuthority());
        assertEquals(uri, launched.intent.getClipData().getItemAt(0).getUri());
        assertTrue((launched.intent.getFlags() & Intent.FLAG_GRANT_WRITE_URI_PERMISSION) != 0);
        writePhoto(uri);
        assertTrue(camera.handleResult(launched.requestCode, Activity.RESULT_OK));
        assertEquals(1, result.calls);
        assertArrayEquals(new Uri[]{uri}, result.value);
        assertFalse(camera.handleResult(launched.requestCode, Activity.RESULT_OK));
        assertEquals(1, result.calls);
    }
    @Test public void emptyOutputCannotCompleteAttendancePhoto() {
        Result result = new Result();
        ShadowActivity.IntentForResult launched = launch(result);
        camera.handleResult(launched.requestCode, Activity.RESULT_OK);
        assertEquals(1, result.calls);
        assertNull(result.value);
    }
    @Test public void cancelledCaptureDiscardsEvenWrittenOutput() throws Exception {
        Result result = new Result();
        ShadowActivity.IntentForResult launched = launch(result);
        writePhoto(output(launched));
        camera.handleResult(launched.requestCode, Activity.RESULT_CANCELED);
        assertEquals(1, result.calls);
        assertNull(result.value);
    }
    @Test public void cancelOrOrganizationSwitchRejectsLateCameraResult() throws Exception {
        Result result = new Result();
        ShadowActivity.IntentForResult launched = launch(result);
        writePhoto(output(launched));
        camera.cancel();
        assertFalse(camera.handleResult(launched.requestCode, Activity.RESULT_OK));
        assertEquals(1, result.calls);
        assertNull(result.value);
    }
    @Test public void oldResultCannotCompleteANewCapture() throws Exception {
        Result first = new Result();
        ShadowActivity.IntentForResult old = launch(first);
        Result next = new Result();
        ShadowActivity.IntentForResult current = launch(next);
        assertNotEquals(old.requestCode, current.requestCode);
        writePhoto(output(current));
        assertFalse(camera.handleResult(old.requestCode, Activity.RESULT_OK));
        assertEquals(0, next.calls);
        assertTrue(camera.handleResult(current.requestCode, Activity.RESULT_OK));
        assertEquals(1, first.calls);
        assertNull(first.value);
        assertArrayEquals(new Uri[]{output(current)}, next.value);
    }
    @Test public void dialogCancelDoesNotOpenAnyPicker() {
        Result result = new Result();
        camera.choose(result);
        ShadowAlertDialog.getLatestAlertDialog().cancel();
        shadowOf(Looper.getMainLooper()).idle();
        assertEquals(1, result.calls);
        assertNull(result.value);
        assertNull(shadowOf(activity).getNextStartedActivityForResult());
    }
    public static class UnavailableCameraActivity extends Activity {
        @Override public void startActivityForResult(Intent intent, int requestCode) {
            throw new ActivityNotFoundException("No camera available");
        }
    }
    @Test public void missingCameraCancelsWithoutGalleryFallback() {
        activity = Robolectric.buildActivity(UnavailableCameraActivity.class).setup().get();
        camera = new AttendanceCamera(activity);
        Result result = new Result();
        camera.choose(result);
        ShadowAlertDialog.getLatestAlertDialog().getButton(AlertDialog.BUTTON_POSITIVE).performClick();
        shadowOf(Looper.getMainLooper()).idle();
        assertEquals(1, result.calls);
        assertNull(result.value);
        assertNull(shadowOf(activity).getNextStartedActivityForResult());
    }
}

