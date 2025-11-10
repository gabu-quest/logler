use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use std::path::Path;
use tokio::sync::mpsc;

#[allow(dead_code)]
pub struct FileWatcher {
    _watcher: RecommendedWatcher,
    receiver: mpsc::Receiver<notify::Result<notify::Event>>,
}

impl FileWatcher {
    #[allow(dead_code)]
    pub fn new<P: AsRef<Path>>(path: P) -> notify::Result<Self> {
        let (tx, receiver) = mpsc::channel(100);

        let mut watcher = notify::recommended_watcher(move |res| {
            let _ = tx.blocking_send(res);
        })?;

        watcher.watch(path.as_ref(), RecursiveMode::NonRecursive)?;

        Ok(Self {
            _watcher: watcher,
            receiver,
        })
    }

    #[allow(dead_code)]
    pub async fn next_event(&mut self) -> Option<notify::Result<notify::Event>> {
        self.receiver.recv().await
    }
}
