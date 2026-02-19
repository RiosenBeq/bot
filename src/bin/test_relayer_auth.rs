use anyhow::Result;
use hmac::{Hmac, Mac};
use sha2::Sha256;
use hex;
use base64::{engine::general_purpose, Engine};
use serde_json::json;

type HmacSha256 = Hmac<Sha256>;

#[tokio::main]
async fn main() -> Result<()> {
    let api_key = "019c6a8b-f262-77ed-b48a-d2b7422c0cb4";
    let api_secret = "PBPkR0BLnZewQCSGJMDCCtvlt6kEBOdH3vUsSGUPfO4=";
    let api_passphrase = "9e4b3fa484e7baae8d1be2155cb1c37e3dfe61e3f0e503807c55ac6676692133";
    let clob_url = "https://clob.polymarket.com";
    let url_path = "/orders-all";

    let secret_bytes = general_purpose::STANDARD.decode(api_secret).unwrap();
    let client = reqwest::Client::new();
    
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs()
        .to_string();

    let message = format!("{}GET{}", timestamp, url_path);
    let mut mac = HmacSha256::new_from_slice(&secret_bytes)?;
    mac.update(message.as_bytes());
    let signature = base64::Engine::encode(&general_purpose::STANDARD, mac.finalize().into_bytes());

    println!("Testing Standard CLOB API Authentication...");
    let resp = client.get(format!("{}{}", clob_url, url_path))
        .header("POLY-API-KEY", api_key)
        .header("POLY-PASSPHRASE", api_passphrase)
        .header("POLY-TIMESTAMP", &timestamp)
        .header("POLY-SIGNATURE", &signature)
        .send()
        .await?;

    println!("Standard CLOB API Status: {}", resp.status());
    if resp.status().is_success() {
        println!("✅ Standard CLOB API credentials are VALID.");
    } else {
        println!("❌ Standard CLOB API credentials are INVALID (or signature format is wrong for CLOB).");
        let text = resp.text().await?;
        println!("Error: {}", text);
    }

    Ok(())
}
