import axios from "axios";
export async function getSignals() { return (await axios.get("/api/signals")).data; }
export async function getMarketOverview() { return (await axios.get("/api/market_overview")).data; }
export async function getFunnel() { return (await axios.get("/api/funnel")).data; }
export async function getSystemHealth() { return (await axios.get("/api/system_health")).data; }
export async function getLearningState() { return (await axios.get("/api/learning_state")).data; }
