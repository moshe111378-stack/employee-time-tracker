package il.co.mishmaron.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.provider.MediaStore;
import android.webkit.ValueCallback;
import android.widget.Toast;
import androidx.core.content.FileProvider;
import java.io.File;
import java.io.IOException;

/** Attendance photos come only from the current camera request, never a document picker. */
final class AttendanceCamera {
    private final Activity activity;
    private ValueCallback<Uri[]> callback;
    private AlertDialog dialog;
    private File output;
    private Uri outputUri;
    private int request = -1;
    private int nextRequest = 1000;

    AttendanceCamera(Activity activity) { this.activity = activity; }

    void choose(ValueCallback<Uri[]> next) {
        cancel();
        callback = next;
        dialog = new AlertDialog.Builder(activity)
            .setTitle("צילום תמונה לדיווח נוכחות")
            .setMessage("יש לצלם תמונה חדשה עכשיו. התמונה תישלח לארגון ותישמר עם דיווח הנוכחות, ותהיה זמינה למנהלים המורשים.")
            .setPositiveButton("צילום תמונה", (d, which) -> {
                if (callback == next) capture();
            })
            .setNegativeButton("ביטול", (d, which) -> {
                if (callback == next) cancel();
            })
            .setOnCancelListener(d -> {
                if (callback == next) cancel();
            }).show();
    }

    private void capture() {
        try {
            File dir = new File(activity.getCacheDir(), "camera");
            if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Camera cache unavailable");
            output = File.createTempFile("attendance-", ".jpg", dir);
            outputUri = FileProvider.getUriForFile(activity, activity.getPackageName() + ".files", output);
            Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            camera.putExtra(MediaStore.EXTRA_OUTPUT, outputUri);
            camera.setClipData(ClipData.newRawUri("attendance photo", outputUri));
            camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            request = nextRequest++;
            if (nextRequest > 64000) nextRequest = 1000;
            activity.startActivityForResult(camera, request);
        } catch (Exception e) {
            cancel();
            Toast.makeText(activity, "לא ניתן לפתוח את המצלמה. נסו לצלם שוב.", Toast.LENGTH_LONG).show();
        }
    }

    boolean handleResult(int requestCode, int resultCode) {
        if (request < 0 || requestCode != request) return false;
        // EXTRA_OUTPUT is authoritative. Never use a returned data URI or a gallery fallback.
        Uri captured = resultCode == Activity.RESULT_OK && outputUri != null &&
            output != null && output.isFile() && output.length() > 0 ? outputUri : null;
        clearCapture(captured == null);
        finish(captured == null ? null : new Uri[]{captured});
        return true;
    }

    void cancel() {
        if (dialog != null) { dialog.dismiss(); dialog = null; }
        clearCapture(true);
        finish(null);
    }

    private void clearCapture(boolean delete) {
        if (outputUri != null) activity.revokeUriPermission(outputUri,
            Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        if (delete && output != null) output.delete();
        // Successful files remain in the private cache while WebView reads them.
        // MainActivity removes previous capture files at the next app startup.
        output = null;
        outputUri = null;
        request = -1;
    }

    private void finish(Uri[] value) {
        ValueCallback<Uri[]> pending = callback;
        callback = null;
        if (pending != null) pending.onReceiveValue(value);
    }
}
