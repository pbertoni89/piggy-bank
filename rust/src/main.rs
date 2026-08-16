mod etica;
mod main_window;

use main_window::PiggyBankApp;
use eframe::NativeOptions;
use tracing_subscriber::FmtSubscriber;

fn main() -> color_eyre::Result<()> {
    // Initialize logging and error handling
    color_eyre::install()?;
    let subscriber = FmtSubscriber::builder()
        .with_max_level(tracing::Level::INFO)
        .finish();
    tracing::subscriber::set_global_default(subscriber)?;

    let options = NativeOptions {
        initial_window_size: Some(egui::vec2(1200.0, 800.0)),
        ..Default::default()
    };

    eframe::run_native(
        "Piggy Bank Rust",
        options,
        Box::new(|cc| Box::new(PiggyBankApp::new(cc))),
    ).unwrap();

    Ok(())
}
