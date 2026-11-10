// Retire previously installed ad workers without affecting either PWA.
self.addEventListener("install", (event) => {
    event.waitUntil(self.skipWaiting());
});
self.addEventListener("activate", (event) => {
    event.waitUntil(self.registration.unregister().then((removed) => {
        if (!removed) throw new Error("Legacy ad worker removal failed");
    }));
});
