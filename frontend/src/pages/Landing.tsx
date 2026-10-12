import { Link } from "react-router-dom";
import { ArrowDown, ArrowRight, ArrowUpRight, AudioLines, BookOpen, Check, FileText, Layers3, Moon, Network, ShieldCheck, Sun } from "lucide-react";
import { BrandMark } from "../components/common/BrandMark";
import { useApp } from "../context/AppContext";
import { useChat } from "../context/ChatContext";
import "./landing.css";

const capabilities = [
  { Icon: BookOpen, tag: "HỎI ĐÁP Y KHOA", name: "Thông tin rõ ràng.\nNguồn để đối chiếu.", text: "Đặt câu hỏi về bệnh phổi, triệu chứng và yếu tố nguy cơ. Đọc câu trả lời cùng nguồn dẫn khi có trong kết quả.", label: "Bắt đầu tìm hiểu", tone: "sage" },
  { Icon: Network, tag: "ĐỒ THỊ TRI THỨC", name: "Kết nối dữ kiện.\nMở rộng góc nhìn.", text: "Tìm hiểu mối liên hệ giữa triệu chứng, bệnh lý và các dữ kiện y khoa trong kho tri thức được cung cấp.", label: "Khám phá tri thức", tone: "blue" },
  { Icon: FileText, tag: "PHÂN TÍCH BỆNH ÁN", name: "Từ nhiều trang tài liệu,\nđến thông tin cô đọng.", text: "Tải bệnh án, xem dữ kiện được trích xuất và đọc bản phân tích ngay trong cuộc trò chuyện của bạn.", label: "Tìm hiểu bệnh án", tone: "sand" },
];

export function Landing() {
  const { summaries } = useChat();
  const { theme, setTheme } = useApp();
  return (
    <main className="landing" id="main-content">
      <nav className="landing-nav" aria-label="Điều hướng giới thiệu">
        <Link to="/" className="landing-brand" aria-label="Medical AI — Trang chủ">
          <BrandMark />
          <span>Medical<span className="brand-ai"> AI</span><small>TRỢ LÝ BỆNH PHỔI</small></span>
        </Link>
        <div className="landing-nav-links"><a href="#capabilities">Khả năng</a><a href="#how-it-works">Cách sử dụng</a><a href="#about">Về trợ lý</a></div>
        <div className="landing-nav-actions">
          <button className="icon-button theme-toggle" onClick={() => setTheme(theme === "light" ? "dark" : "light")} aria-label={theme === "light" ? "Chuyển sang giao diện tối" : "Chuyển sang giao diện sáng"} title="Đổi giao diện">{theme === "light" ? <Moon size={18} /> : <Sun size={18} />}</button>
          <Link to="/chat" className="landing-nav-chat">Mở trợ lý <ArrowUpRight size={17} /></Link>
        </div>
      </nav>
      <section className="landing-hero" aria-labelledby="hero-title">
        <div className="landing-copy">
          <span className="landing-eyebrow"><span /> TRI THỨC Y KHOA, TRONG TẦM TAY</span>
          <h1 id="hero-title">Hiểu thêm.<br /><em>Chủ động hơn.</em></h1>
          <p>Mỗi câu hỏi là một bước để hiểu hơn về sức khỏe hô hấp. Cùng Medical AI tìm thông tin, kết nối tri thức và khám phá dữ kiện trong bệnh án.</p>
          <div className="landing-cta"><Link to="/chat" className="landing-primary">Bắt đầu chat <ArrowRight size={19} /></Link>{summaries[0] ? <Link to={`/chat/${summaries[0].id}`} className="landing-secondary">Tiếp tục hội thoại <ArrowUpRight size={17} /></Link> : <a href="#capabilities" className="landing-secondary">Khám phá khả năng <ArrowDown size={17} /></a>}</div>
          <div className="hero-details"><span><Check size={15} /> Hỗ trợ tiếng Việt</span><span><Check size={15} /> Tra cứu có dẫn chứng</span></div>
          <div className="landing-voice"><span className="voice-small-icon"><AudioLines size={21} /></span><div>Đôi khi, chỉ cần nói ra câu hỏi.<small>Trợ lý giọng nói, ngay trong khung chat.</small></div></div>
        </div>
        <div className="landing-visual">
          <div className="landing-art">
            <div className="art-topline"><span><span className="status-dot" /> KHÁM PHÁ TRI THỨC</span><span>MEDICAL AI</span></div>
            <div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" />
            <span className="art-coordinate coordinate-left">RESPIRATORY<br />KNOWLEDGE</span>
            <img className="art-banner" src="/assets/lung-knowledge-teal.png" width="1280" height="1280" alt="Minh họa lá phổi và mạng lưới kết nối tri thức y khoa" fetchPriority="high" />
            <div className="art-bottomline"><span>Nhìn sâu hơn vào<br /><strong>từng kết nối y khoa.</strong></span><Network size={28} strokeWidth={1.3} /></div>
          </div>
          <div className="art-note"><span className="art-note-icon"><BookOpen size={21} /></span><div>Tri thức có cơ sở<small>Kết nối câu hỏi với nguồn tài liệu</small></div><span className="art-note-check"><Check size={14} /></span></div>
          <div className="art-caption"><span /> Thông tin để hiểu. Dữ kiện để đối chiếu.</div>
        </div>
      </section>
      <div className="landing-feature-strip" aria-label="Khả năng của trợ lý"><span>MỘT KHÔNG GIAN.<br /><strong>NHIỀU CÁCH TÌM HIỂU.</strong></span><div><BookOpen size={20} /> Hỏi đáp có dẫn chứng</div><div><Network size={20} /> Kết nối tri thức</div><div><FileText size={20} /> Phân tích bệnh án</div><div><AudioLines size={20} /> Trò chuyện giọng nói</div></div>
      <section id="capabilities" className="landing-capabilities" aria-labelledby="capabilities-title">
        <div className="landing-section-title"><div><span className="section-eyebrow">ĐỒNG HÀNH CÙNG BẠN</span><h2 id="capabilities-title">Từ câu hỏi đầu tiên,<br />đến góc nhìn rõ ràng hơn.</h2></div><p>Những công cụ cần thiết để bạn chủ động<br className="desktop-break" /> tìm hiểu thông tin về sức khỏe hô hấp.</p></div>
        <div className="landing-cards">{capabilities.map(({ Icon, tag, name, text, label, tone }, i) => <article key={tag} className={`capability-card ${tone}`}><div className="capability-card-top"><span className="capability-icon"><Icon size={25} strokeWidth={1.6} /></span><span className="capability-number">0{i + 1}</span></div><span className="capability-tag">{tag}</span><h3>{name}</h3><p>{text}</p><Link to="/chat">{label} <ArrowUpRight size={18} /></Link></article>)}</div>
      </section>
      <section id="how-it-works" className="landing-workflow" aria-labelledby="workflow-title">
        <div className="workflow-visual" aria-hidden="true"><div className="document-stack stack-back" /><div className="document-stack stack-front"><span className="document-label"><FileText size={19} /> BỆNH ÁN CỦA BẠN</span><div className="document-line long" /><div className="document-line" /><div className="document-line short" /><div className="document-divider" /><span className="document-row"><Check size={14} /> Thông tin được trích xuất</span><span className="document-row"><Check size={14} /> Dữ kiện được trình bày rõ ràng</span><span className="document-row"><Check size={14} /> Nội dung để bạn đối chiếu</span><div className="document-bottom"><BrandMark /><span>Medical AI<small>Hỗ trợ phân tích bệnh án</small></span><Layers3 size={20} /></div></div><span className="workflow-badge"><Check size={14} /> Bạn kiểm soát bước gửi</span></div>
        <div className="workflow-copy"><span className="section-eyebrow">ĐƠN GIẢN TỪ BƯỚC ĐẦU</span><h2 id="workflow-title">Một cuộc trò chuyện.<br />Nhiều điều được làm rõ.</h2><ol className="workflow-steps"><li><span>01</span><div><h3>Đặt câu hỏi hoặc thêm bệnh án</h3><p>Nhập điều bạn muốn tìm hiểu, hoặc chọn tài liệu để phân tích.</p></div></li><li><span>02</span><div><h3>Gửi khi bạn đã sẵn sàng</h3><p>Tệp chỉ được tải lên khi bạn nhấn Gửi. Bạn có thể gỡ tệp trước đó.</p></div></li><li><span>03</span><div><h3>Đọc, đối chiếu và hỏi tiếp</h3><p>Xem kết quả trong hội thoại, kiểm tra dữ kiện và tiếp tục tìm hiểu.</p></div></li></ol><Link to="/chat" className="workflow-link">Trải nghiệm Medical AI <ArrowRight size={18} /></Link></div>
      </section>
      <section id="about" className="landing-trust"><span className="trust-icon"><ShieldCheck size={29} strokeWidth={1.5} /></span><div><span className="section-eyebrow">HIỂU THÔNG TIN. GIỮ QUYỀN CHỦ ĐỘNG.</span><h2>Trợ lý tra cứu, đồng hành cùng bạn.</h2><p>Thông tin do AI cung cấp nhằm mục đích tham khảo, không thay thế chẩn đoán hoặc tư vấn của bác sĩ. Với lượt đánh giá tương tác, bạn luôn kiểm tra và xác nhận dữ kiện trước khi gửi.</p></div><Link to="/chat">Đặt câu hỏi đầu tiên <ArrowUpRight size={19} /></Link></section>
      <footer className="landing-footer"><Link to="/" className="footer-brand"><BrandMark /><strong>Medical AI</strong></Link><span>Tri thức y khoa, gần hơn với bạn.</span><a href="#hero-title">Về đầu trang <ArrowUpRight size={15} /></a></footer>
    </main>
  );
}
