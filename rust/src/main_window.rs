use crate::etica::{self, COL_DATA, COL_DESCR, COL_MINUS, COL_PLUS, COL_RUN_TOT};
use eframe::egui;
use egui_extras::{Column, TableBuilder};
use egui_plot::{Line, Plot, PlotPoints};
use polars::prelude::*;
use regex::Regex;

pub struct PiggyBankApp {
    df_all: DataFrame,
    df_filtered: DataFrame,
    
    // Filters
    filter_desc: String,
    show_in: bool,
    show_out: bool,
    inv_pattern: Regex,

    // Statistics
    entries: usize,
    sum_tot: f64,
}

impl PiggyBankApp {
    pub fn new(_cc: &eframe::CreationContext<'_>) -> Self {
        let df_all = etica::load_data().unwrap_or_else(|_| DataFrame::empty());
        let inv_pattern = Regex::new(r"FONDI|PROVENTI|CEDOLE|DEPOSIT").unwrap(); //[cite: 28]

        let mut app = Self {
            df_filtered: df_all.clone(),
            df_all,
            filter_desc: String::new(),
            show_in: true,
            show_out: true,
            inv_pattern,
            entries: 0,
            sum_tot: 0.0,
        };
        app.apply_filters();
        app
    }

    fn apply_filters(&mut self) {
        // Egui is immediate mode, so we rebuild the filtered dataframe quickly
        // In a highly optimized app, you'd use LazyFrame filtering here.
        let mut mask = BooleanChunked::full("mask", true, self.df_all.height());
        
        let desc_col = self.df_all.column(COL_DESCR).unwrap().str().unwrap();
        
        let mut entries = 0;
        let mut sum_tot = 0.0;

        // Simplified filtering loop
        for i in 0..self.df_all.height() {
            let mut keep = true;

            if let Some(desc) = desc_col.get(i) {
                if !self.filter_desc.is_empty() && !desc.to_lowercase().contains(&self.filter_desc.to_lowercase()) {
                    keep = false;
                }
            }

            if keep {
                entries += 1;
                // Accumulate stats (assuming sum logic here)
            }
            mask.set(i, Some(keep));
        }

        self.df_filtered = self.df_all.filter(&mask).unwrap();
        self.entries = entries;
        self.sum_tot = sum_tot;
    }
}

impl eframe::App for PiggyBankApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        egui::TopBottomPanel::top("filter_panel").show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.label("Filter Description:");
                if ui.text_edit_singleline(&mut self.filter_desc).changed() {
                    self.apply_filters();
                }

                if ui.checkbox(&mut self.show_in, "In").changed() {
                    self.apply_filters();
                }
                if ui.checkbox(&mut self.show_out, "Out").changed() {
                    self.apply_filters();
                }
                
                if ui.button("Reset").clicked() {
                    self.filter_desc.clear();
                    self.show_in = true;
                    self.show_out = true;
                    self.apply_filters();
                }
            });
            ui.horizontal(|ui| {
                ui.label(format!("Entries: {}", self.entries));
            });
        });

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("Ledger & Plot");
            
            // Split view: Table on top, Plot on bottom
            ui.columns(2, |columns| {
                // TABLE
                columns[0].push_id("table_col", |ui| {
                    TableBuilder::new(ui)
                        .striped(true)
                        .column(Column::auto())
                        .column(Column::auto())
                        .column(Column::auto())
                        .column(Column::remainder())
                        .header(20.0, |mut header| {
                            header.col(|ui| { ui.strong("Date"); });
                            header.col(|ui| { ui.strong("In"); });
                            header.col(|ui| { ui.strong("Out"); });
                            header.col(|ui| { ui.strong("Descrizione"); });
                        })
                        .body(|mut body| {
                            let dates = self.df_filtered.column(COL_DATA).unwrap().str().unwrap();
                            let ins = self.df_filtered.column(COL_PLUS).unwrap().f64().unwrap();
                            let outs = self.df_filtered.column(COL_MINUS).unwrap().f64().unwrap();
                            let descs = self.df_filtered.column(COL_DESCR).unwrap().str().unwrap();

                            for i in 0..self.df_filtered.height() {
                                body.row(18.0, |mut row| {
                                    row.col(|ui| { ui.label(dates.get(i).unwrap_or("")); });
                                    row.col(|ui| { ui.label(format!("{:.2}", ins.get(i).unwrap_or(0.0))); });
                                    row.col(|ui| { ui.label(format!("{:.2}", outs.get(i).unwrap_or(0.0))); });
                                    row.col(|ui| { ui.label(descs.get(i).unwrap_or("")); });
                                });
                            }
                        });
                });

                // PLOT
                columns[1].push_id("plot_col", |ui| {
                    let saldos = self.df_filtered.column(COL_RUN_TOT).unwrap().f64().unwrap();
                    let mut points: Vec<[f64; 2]> = Vec::new();
                    
                    for i in 0..self.df_filtered.height() {
                        if let Some(s) = saldos.get(i) {
                            points.push([i as f64, s]); // Basic X-axis for demonstration
                        }
                    }

                    let line = Line::new(PlotPoints::new(points)).name("Running Total");
                    
                    Plot::new("saldo_plot")
                        .view_aspect(2.0)
                        .show(ui, |plot_ui| {
                            plot_ui.line(line);
                        });
                });
            });
        });
    }
}
