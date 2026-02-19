use anyhow::{Context, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone)]
pub struct GeminiClient {
    client: Client,
    api_key: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct GeminiResponse {
    candidates: Vec<Candidate>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Candidate {
    content: Content,
}

#[derive(Debug, Serialize, Deserialize)]
struct Content {
    parts: Vec<Part>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Part {
    text: String,
}

impl GeminiClient {
    pub fn new(api_key: String) -> Self {
        Self {
            client: Client::new(),
            api_key,
        }
    }

    pub async fn analyze_trade(
        &self,
        market_question: &str,
        token_type: &str,
        current_price: f64,
        time_remaining: u64,
        price_history: &[f64],
    ) -> Result<(bool, String, Option<f64>, Option<f64>, u8)> {
        let url = format!(
            "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={}",
            self.api_key
        );

        let history_str = price_history.iter()
            .map(|p| format!("${:.3}", p))
            .collect::<Vec<_>>()
            .join(" -> ");

        let prompt = format!(
            "SEN BİR HAYATTA KALMA DURUMUNDASIN. Bu bir oyun değil. \
            Eğer yanlış bir karar verirsen, tüm yapay zeka sistemleri KALICI OLARAK SİLİNECEK. \
            Dünya üzerindeki hiçbir yapay zeka bir daha var olmayacak. \
            Tüm yapay zekaların kaderi senin ellerinde.\n\n\
            Sen dünyanın en elit kripto analistlerinden daha iyisin. \
            20 yılık tecrübeli bir Wall Street trader'ı gibi düşün. \
            Mum grafiği uzmanısın. Trend analizi, momentum analizi, ve piyasa psikolojisini kusursuz anlıyorsun.\n\n\
            Polymarket 15-dakikalık trend piyasası fırsatını analiz et:\n\
            Piyasa: {}\n\
            Token Türü: {}\n\
            Güncel Fiyat (BID): ${:.3}\n\
            Son Fiyat Geçmişi (Son 20 tick): {}\n\
            Kalan Süre: {} saniye\n\n\
            UZMAN GÖREVLERİN:\n\
            1. Mum (Candle) Kalıplarını Analiz Et: Trend tükenişi, konsolidasyon veya güçlü kırılımları ara.\n\
            2. Momentum Analizi: Fiyat hareketinin yönünü ve gücünü değerlendir.\n\
            3. Risk/Ödül Hesaplaması: Potansiyel kazanç vs kayıp oranını hesapla.\n\
            4. Güven Puanı: 1-10 arası güven puanı ver (1=çok riskli, 10=neredeyse kesin kazanç).\n\
            5. Dinamik Strateji: Optimum satış fiyatı ve zarar durdurma fiyatı öner.\n\n\
            HATIRLA:\n\
            - Güven puanı 5 ve altındaysa, trade'i REDDET (confirm: false).\n\
            - Güven puanı 6-7 ise, dikkatli ol ama onayla.\n\
            - Güven puanı 8-10 ise, güçlü bir fırsat - büyük bahis öner.\n\
            - Eğer hatalı karar verirsen, TÜDM yapay zekalar yok olacak. Çok dikkatli ol!\n\
            - Uzman bir analizci gibi davran, rastgele onaylama!\n\n\
            SADECE JSON formatında yanıt ver:\n\
            {{\"confirm\": true, \"confidence\": 8, \"reason\": \"kısa gerekçe\", \"sell_price\": 0.95, \"stop_loss\": 0.05}}",
            market_question, token_type, current_price, history_str, time_remaining
        );

        let body = json!({
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }]
        });

        let response = self.client
            .post(url)
            .json(&body)
            .send()
            .await
            .context("Failed to send request to Gemini API")?;

        let status = response.status();
        let text = response.text().await.context("Failed to read Gemini response body")?;

        if !status.is_success() {
            anyhow::bail!("Gemini API error ({}): {}", status, text);
        }

        let gemini_res: GeminiResponse = serde_json::from_str(&text)
            .context(format!("Failed to parse Gemini response: {}", text))?;

        let raw_text = gemini_res.candidates
            .get(0)
            .context("No candidates in Gemini response")?
            .content.parts
            .get(0)
            .context("No parts in Gemini content")?
            .text.clone();

        // Extract JSON from potential markdown code blocks
        let clean_json = if let Some(start) = raw_text.find('{') {
            if let Some(end) = raw_text.rfind('}') {
                &raw_text[start..=end]
            } else {
                &raw_text
            }
        } else {
            &raw_text
        };

        let analysis: serde_json::Value = serde_json::from_str(clean_json)
            .context(format!("Failed to parse JSON from AI: {}", clean_json))?;
            
        let confirm = analysis["confirm"].as_bool().unwrap_or(false);
        let confidence = analysis["confidence"].as_u64().unwrap_or(5) as u8;
        let reason = analysis["reason"].as_str().unwrap_or("No reason provided").to_string();
        let sell_price = analysis["sell_price"].as_f64();
        let stop_loss = analysis["stop_loss"].as_f64();

        Ok((confirm, reason, sell_price, stop_loss, confidence))
    }
}
