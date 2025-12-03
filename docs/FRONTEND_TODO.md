## Frontend / Live Log TODOs

- [ ] Push filtering down to Rust/web API: accept thread/level/query params on `/api/files/open` and `/api/files/open_many` so the browser never receives unused rows; add server-side cap per request.
- [ ] Stream-time filtering: allow WebSocket follow to send active filters (levels + threads) and pre-filter on the backend before pushing frames.
- [ ] Virtualized list component reuse: extract the log/thread virtualization into a tiny helper to avoid duplicating math and to support other panes (traces, correlations).
- [ ] Further perf tuning: measure row height dynamically once to avoid over/under render drift; add requestAnimationFrame throttling to scroll handlers.
- [ ] Keyboard accessibility: shortcuts to jump between threads, toggle auto-scroll, and focus search inputs.
- [ ] UI polish: highlight selected threads in the stream, add per-thread color chips, and show sticky headers for active filters.
- [ ] Offline bundling: replace CDN fonts/JS with locally bundled assets (Alpine/HTMX) and set cache headers.
- [ ] Test coverage: add Playwright smoke for virtualization (scrolling large datasets) and thread selection while following live logs.
- [ ] Sampling/limit controls: expose a UI slider for max rows kept/rendered, and surface backpressure indicators when data is being dropped.
- [ ] Tailwind pipeline: wire `npm run build:css` and ensure wheel publish runs the Tailwind build step.
