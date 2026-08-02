use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;

#[derive(Debug)]
struct CancellationState {
    cancelled: AtomicBool,
    spawns_in_progress: AtomicUsize,
}

#[derive(Debug)]
pub(crate) struct SpawnPermit {
    state: Arc<CancellationState>,
}

impl Drop for SpawnPermit {
    fn drop(&mut self) {
        self.state.spawns_in_progress.fetch_sub(1, Ordering::AcqRel);
    }
}

#[derive(Clone, Debug)]
pub(crate) struct CancellationToken {
    state: Arc<CancellationState>,
}

impl CancellationToken {
    pub(crate) fn new() -> Self {
        Self {
            state: Arc::new(CancellationState {
                cancelled: AtomicBool::new(false),
                spawns_in_progress: AtomicUsize::new(0),
            }),
        }
    }

    pub(crate) fn cancel(&self) -> bool {
        let first_transition = !self.state.cancelled.swap(true, Ordering::AcqRel);
        while self.state.spawns_in_progress.load(Ordering::Acquire) != 0 {
            thread::yield_now();
        }
        first_transition
    }

    pub(crate) fn is_cancelled(&self) -> bool {
        self.state.cancelled.load(Ordering::Acquire)
    }

    pub(crate) fn try_begin_spawn(&self) -> Option<SpawnPermit> {
        if self.is_cancelled() {
            return None;
        }

        self.state.spawns_in_progress.fetch_add(1, Ordering::AcqRel);

        if self.is_cancelled() {
            self.state.spawns_in_progress.fetch_sub(1, Ordering::AcqRel);
            return None;
        }

        Some(SpawnPermit {
            state: Arc::clone(&self.state),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::CancellationToken;
    use std::sync::mpsc;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn cancellation_is_shared_monotonic_and_reports_first_transition() {
        let token = CancellationToken::new();
        let clone = token.clone();

        assert!(!token.is_cancelled());
        assert!(clone.cancel());
        assert!(token.is_cancelled());
        assert!(!token.cancel());
        assert!(clone.is_cancelled());
        assert!(token.try_begin_spawn().is_none());
    }

    #[test]
    fn cancellation_waits_for_in_progress_spawn_to_finish() {
        let token = CancellationToken::new();
        let permit = token.try_begin_spawn().expect("permiso inicial");
        let clone = token.clone();
        let (done_sender, done_receiver) = mpsc::channel();

        let handle = thread::spawn(move || {
            let first_transition = clone.cancel();
            done_sender
                .send(first_transition)
                .expect("resultado de cancelación");
        });

        while !token.is_cancelled() {
            thread::yield_now();
        }
        assert!(done_receiver.try_recv().is_err());

        drop(permit);
        assert!(done_receiver
            .recv_timeout(Duration::from_secs(1))
            .expect("cancelación terminada"));
        handle.join().expect("hilo de cancelación");
    }
}
