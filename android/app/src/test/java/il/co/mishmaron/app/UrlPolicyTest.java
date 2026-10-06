package il.co.mishmaron.app;
import org.junit.Test;
import static org.junit.Assert.*;
public class UrlPolicyTest {
    static final String BASE="https://client.example.com/";
    @Test public void tenantIsolation(){
        assertTrue(UrlPolicy.sameOrigin(BASE,"https://client.example.com/admin"));
        assertTrue(UrlPolicy.sameOrigin(BASE,"https://CLIENT.example.com:443/event/1"));
        assertFalse(UrlPolicy.sameOrigin(BASE,"https://other.example.com/"));
        assertFalse(UrlPolicy.sameOrigin(BASE,"https://client.example.com.evil.com/"));
        assertFalse(UrlPolicy.sameOrigin(BASE,"https://client.example.com@evil.com/"));
        assertFalse(UrlPolicy.sameOrigin(BASE,"https://evil@client.example.com/"));
        assertFalse(UrlPolicy.sameOrigin(BASE,"http://client.example.com/"));
        assertFalse(UrlPolicy.sameOrigin(BASE,"file:///data/data/il.co.mishmaron.app/"));
        assertFalse(UrlPolicy.sameOrigin(BASE,"javascript:alert(1)"));
        assertFalse(UrlPolicy.sameOrigin(BASE,null));
    }
    @Test public void registryRejectsInvalidRoots(){
        assertTrue(UrlPolicy.organizationRoot(BASE));
        assertFalse(UrlPolicy.organizationRoot(BASE+"admin"));
        assertFalse(UrlPolicy.organizationRoot(BASE+"?token=secret"));
        assertFalse(UrlPolicy.organizationRoot("https://localhost/"));
        assertFalse(UrlPolicy.organizationRoot("https://127.0.0.1/"));
        assertFalse(UrlPolicy.organizationRoot("https://client.example.com:8080/"));
    }
}
