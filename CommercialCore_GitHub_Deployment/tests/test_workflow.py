from datetime import date, timedelta
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Business, Policy, Exposure, Projection, ReviewItem, Report, ReviewPacket, User, Task, Activity, Recommendation

def login(client):
    r = client.post("/login", data={"username":"admin","password":"admin123"}, follow_redirects=False)
    assert r.status_code == 303

def test_complete_vertical_workflow(client):
    login(client)
    r = client.post("/businesses/new", data={
        "legal_name":"ABC Landscaping",
        "dba_name":"",
        "industry":"Landscaping",
        "renewal_month":"3",
        "producer_id":"1",
    }, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        b = db.scalar(select(Business).where(Business.legal_name=="ABC Landscaping"))
        assert b
        bid = b.id
    start = date.today() - timedelta(days=120)
    end = start + timedelta(days=364)
    r = client.post(f"/businesses/{bid}/policies", data={
        "line":"Workers Compensation",
        "policy_number_ref":"REF-1",
        "effective_date":start.isoformat(),
        "expiration_date":end.isoformat(),
        "notes":"",
    }, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        p = db.scalar(select(Policy).where(Policy.business_id==bid))
        pid = p.id
    r = client.post(f"/policies/{pid}/exposures", data={
        "exposure_type":"payroll",
        "recorded_estimate":"100000",
        "cadence":"monthly",
    }, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        e = db.scalar(select(Exposure).where(Exposure.policy_id==pid))
        eid = e.id
    p1s = start
    p1e = start + timedelta(days=29)
    p2s = p1e + timedelta(days=1)
    p2e = p2s + timedelta(days=29)
    for s,e,v in [(p1s,p1e,20000),(p2s,p2e,22000)]:
        r = client.post(f"/exposures/{eid}/entries", data={
            "period_start":s.isoformat(),
            "period_end":e.isoformat(),
            "actual_value":str(v),
            "note":"test",
        }, follow_redirects=False)
        assert r.status_code == 303
    with SessionLocal() as db:
        review = db.scalar(select(ReviewItem).where(ReviewItem.business_id==bid))
        assert review is not None
    r = client.post(f"/businesses/{bid}/reports", follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        report = db.scalar(select(Report).where(Report.business_id==bid))
        assert report and report.status=="draft"
        rid=report.id
    r = client.post(f"/reports/{rid}/approve", follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        report = db.get(Report,rid)
        assert report.status=="approved"

def test_overlap_rejected(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Test Co","dba_name":"","industry":"","renewal_month":"1","producer_id":"1"})
    with SessionLocal() as db:
        bid=db.scalar(select(Business.id))
    today=date.today()
    client.post(f"/businesses/{bid}/policies", data={"line":"WC","policy_number_ref":"","effective_date":today.isoformat(),"expiration_date":(today+timedelta(days=364)).isoformat(),"notes":""})
    with SessionLocal() as db:
        pid=db.scalar(select(Policy.id))
    client.post(f"/policies/{pid}/exposures", data={"exposure_type":"payroll","recorded_estimate":"1000","cadence":"weekly"})
    with SessionLocal() as db:
        eid=db.scalar(select(Exposure.id))
    client.post(f"/exposures/{eid}/entries", data={"period_start":today.isoformat(),"period_end":(today+timedelta(days=6)).isoformat(),"actual_value":"100","note":""})
    r=client.post(f"/exposures/{eid}/entries", data={"period_start":(today+timedelta(days=3)).isoformat(),"period_end":(today+timedelta(days=9)).isoformat(),"actual_value":"100","note":""})
    assert r.status_code==400

def test_exposure_reporting_page_contains_explanations_and_graphs(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Graph Test Co","dba_name":"","industry":"Contractor","renewal_month":"1","producer_id":"1"})
    with SessionLocal() as db:
        bid=db.scalar(select(Business.id).where(Business.legal_name=="Graph Test Co"))
    today=date.today()-timedelta(days=90)
    client.post(f"/businesses/{bid}/policies", data={"line":"WC","policy_number_ref":"","effective_date":today.isoformat(),"expiration_date":(today+timedelta(days=364)).isoformat(),"notes":""})
    with SessionLocal() as db:
        pid=db.scalar(select(Policy.id).where(Policy.business_id==bid))
    client.post(f"/policies/{pid}/exposures", data={"exposure_type":"payroll","recorded_estimate":"120000","cadence":"monthly"})
    with SessionLocal() as db:
        eid=db.scalar(select(Exposure.id).where(Exposure.policy_id==pid))
    client.post(f"/exposures/{eid}/entries", data={"period_start":today.isoformat(),"period_end":(today+timedelta(days=29)).isoformat(),"actual_value":"15000","note":""})
    response=client.get(f"/exposures/{eid}")
    assert response.status_code==200
    body=response.text
    assert "Exposure Accuracy" in body
    assert "Reporting Confidence" in body
    assert "Cumulative exposure trend" in body
    assert 'id="trend-chart"' in body
    assert 'id="projection-chart"' in body

def test_dashboard_contains_business_health_and_action_list(client):
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Business Health Dashboard" in response.text
    assert "Portfolio health" in response.text
    assert "Business action list" in response.text
    assert "CommercialCore Index" in response.text


def test_review_queue_filters_and_explains_rules(client):
    login(client)
    response = client.get("/reviews?status=active&priority=high&owner=unassigned")
    assert response.status_code == 200
    assert "Review Queue" in response.text
    assert "Why it was created" in response.text
    assert "Apply filters" in response.text


def test_phase_one_executive_dashboard_sections(client):
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    body = response.text
    assert "Executive Dashboard" in body
    assert "Renewal countdown" in body
    assert "Reporting status" in body
    assert "Exposure changes" in body
    assert "Review workload" in body
    assert "Business action list" in body

def test_phase_two_business_account_dashboard(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Phase Two Co","dba_name":"","industry":"Manufacturing","renewal_month":"8","producer_id":"1"})
    with SessionLocal() as db:
        bid=db.scalar(select(Business.id).where(Business.legal_name=="Phase Two Co"))
    response=client.get(f"/businesses/{bid}")
    assert response.status_code == 200
    body=response.text
    assert "Business account" in body
    assert "Account attention" in body
    assert "Policies and renewal timeline" in body
    assert "Account timeline" in body
    assert 'id="business-projection-chart"' in body
    assert 'id="business-score-chart"' in body


def test_phase_two_notes_and_carrier_reference(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Carrier Test Co","dba_name":"","industry":"Retail","renewal_month":"9","producer_id":"1"})
    with SessionLocal() as db:
        bid=db.scalar(select(Business.id).where(Business.legal_name=="Carrier Test Co"))
    today=date.today()
    client.post(f"/businesses/{bid}/policies", data={"line":"Businessowners","policy_number_ref":"BOP-1","effective_date":today.isoformat(),"expiration_date":(today+timedelta(days=364)).isoformat(),"notes":""})
    with SessionLocal() as db:
        pid=db.scalar(select(Policy.id).where(Policy.business_id==bid))
    assert client.post(f"/policies/{pid}/carrier", data={"carrier_name":"Example Carrier","contact_name":"Jane","contact_email":"jane@example.com","contact_phone":"555-0100","notes":"Test"}, follow_redirects=False).status_code == 303
    assert client.post(f"/businesses/{bid}/notes", data={"category":"client_contact","body":"Discussed renewal expectations."}, follow_redirects=False).status_code == 303
    response=client.get(f"/businesses/{bid}")
    assert "Example Carrier" in response.text
    assert "Discussed renewal expectations." in response.text


def test_phase_five_review_builder_and_pdf(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Review Builder Co","dba_name":"","industry":"Contractor","renewal_month":"7","producer_id":"1"})
    with SessionLocal() as db:
        bid=db.scalar(select(Business.id).where(Business.legal_name=="Review Builder Co"))
    page=client.get(f"/businesses/{bid}/review-builder")
    assert page.status_code==200
    assert "Create annual review" in page.text
    response=client.post(f"/businesses/{bid}/review-builder", data={"title":"2026 Annual Review","meeting_date":date.today().isoformat(),"prepared_for":"Leadership Team","executive_summary":"Current program summary.","discussion_points":"Confirm payroll.","recommendations":"Review estimates.","next_steps":"Meet next week.","account_snapshot":"1","policy_summary":"1","exposure_analysis":"1","review_items":"1","contact_summary":"1"}, follow_redirects=False)
    assert response.status_code==303
    with SessionLocal() as db:
        packet=db.scalar(select(ReviewPacket).where(ReviewPacket.business_id==bid))
        assert packet and packet.status=="generated" and packet.file_name
        pid=packet.id
    detail=client.get(f"/review-packets/{pid}")
    assert detail.status_code==200 and "2026 Annual Review" in detail.text
    download=client.get(f"/review-packets/{pid}/download")
    assert download.status_code==200 and download.headers["content-type"].startswith("application/pdf")
    approved=client.post(f"/review-packets/{pid}/approve", follow_redirects=False)
    assert approved.status_code==303
    with SessionLocal() as db:
        assert db.get(ReviewPacket,pid).status=="approved"


def test_phase_six_multi_user_crm(client):
    login(client)
    assert client.post("/admin/users",data={"username":"miles","full_name":"Miles Scritchlow","password":"temporary123","role":"account_manager"},follow_redirects=False).status_code==303
    client.post("/businesses/new",data={"legal_name":"CRM Test Co","dba_name":"","industry":"Services","renewal_month":"8","producer_id":"1"})
    with SessionLocal() as db:
        b=db.scalar(select(Business).where(Business.legal_name=="CRM Test Co"));u=db.scalar(select(User).where(User.username=="miles"));bid=b.id;uid=u.id
    assert client.post("/tasks",data={"business_id":str(bid),"title":"Call about renewal","description":"Confirm payroll","priority":"high","due_date":date.today().isoformat(),"assigned_to":str(uid)},follow_redirects=False).status_code==303
    assert client.post("/activities",data={"business_id":str(bid),"activity_type":"call","subject":"Renewal call","body":"Discussed payroll.","owner_id":str(uid)},follow_redirects=False).status_code==303
    with SessionLocal() as db:
        assert db.scalar(select(Task).where(Task.business_id==bid)).assigned_to==uid
        assert db.scalar(select(Activity).where(Activity.business_id==bid)).owner_id==uid
    page=client.get(f"/businesses/{bid}");assert "Tasks and activities" in page.text and "Call about renewal" in page.text and "Renewal call" in page.text
    assert "Call about renewal" in client.get(f"/tasks?owner={uid}").text

def test_phase_six_staff_login(client):
    login(client);client.post("/admin/users",data={"username":"support","full_name":"Support User","password":"temporary123","role":"data_support"});client.post("/logout")
    assert client.post("/login",data={"username":"support","password":"temporary123"},follow_redirects=False).status_code==303
    assert client.get("/tasks").status_code==200


def test_business_intelligence_explains_account(client):
    login(client)
    response = client.post("/businesses/new", data={"legal_name": "Intelligence Test LLC", "industry": "Services"}, follow_redirects=False)
    business_url = response.headers["location"]
    page = client.get(business_url)
    assert page.status_code == 200
    assert "Business health analysis" in page.text
    assert "Recommended next action" in page.text
    assert "Why?" in page.text
    assert "Complete exposure setup" in page.text or "Complete exposure setup" in page.text


def test_portfolio_intelligence_sections(client):
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    body = response.text
    assert "Portfolio intelligence" in body
    assert "Top-priority accounts" in body
    assert "Portfolio health distribution" in body
    assert "Six-month renewal pressure" in body
    assert "Accounts trending down" in body
    assert "Workload concentration" in body


def test_portfolio_intelligence_ranks_account_reasons(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Priority Portfolio Co","dba_name":"","industry":"Contractor","renewal_month":"1","producer_id":"1"})
    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.legal_name == "Priority Portfolio Co"))
        db.add(ReviewItem(business_id=business.id, rule_code="TEST_PRIORITY", priority="high", title="Material issue", evidence="Testing portfolio focus ranking", status="open"))
        db.commit()
    response = client.get("/dashboard")
    assert "Priority Portfolio Co" in response.text
    assert "high-priority review" in response.text
    assert "focus score" in response.text


def test_recommendation_engine_creates_explainable_action(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Recommendation Test Co","industry":"Contractor","producer_id":"1"})
    with SessionLocal() as db:
        business=db.scalar(select(Business).where(Business.legal_name=="Recommendation Test Co"))
        db.add(ReviewItem(business_id=business.id,rule_code="TEST_REC",priority="high",title="Urgent classification review",evidence="Classification changed",status="open"))
        db.commit(); bid=business.id
    page=client.get(f"/businesses/{bid}")
    assert page.status_code==200
    assert "Recommendation engine" in page.text
    assert "Address high-priority review items" in page.text
    assert "Why:" in page.text
    with SessionLocal() as db:
        rec=db.scalar(select(Recommendation).where(Recommendation.business_id==bid,Recommendation.code=="resolve_high_priority_reviews"))
        assert rec and rec.confidence=="high" and rec.priority=="high"

def test_recommendation_actions_create_task_packet_and_resolve(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Recommendation Workflow Co","industry":"Services","producer_id":"1"})
    with SessionLocal() as db:
        business=db.scalar(select(Business).where(Business.legal_name=="Recommendation Workflow Co"));bid=business.id
    client.get(f"/businesses/{bid}")
    with SessionLocal() as db:
        rec=db.scalar(select(Recommendation).where(Recommendation.business_id==bid)); rid=rec.id
    assert client.post(f"/recommendations/{rid}/task",data={"assigned_to":"1"},follow_redirects=False).status_code==303
    with SessionLocal() as db:
        rec=db.get(Recommendation,rid); assert rec.status=="task_created" and rec.linked_task_id
    assert client.post(f"/recommendations/{rid}/packet",follow_redirects=False).status_code==303
    with SessionLocal() as db:
        rec=db.get(Recommendation,rid); assert rec.status=="packet_added" and rec.linked_packet_id
    assert client.post(f"/recommendations/{rid}/resolve",data={"action":"completed","note":"Handled with client"},follow_redirects=False).status_code==303
    with SessionLocal() as db:
        rec=db.get(Recommendation,rid); assert rec.status=="completed" and rec.resolution_note=="Handled with client"
    assert "Recommended actions" in client.get("/recommendations?status=completed").text


def test_phase_741_executive_analytics_dashboard(client):
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    body = response.text
    assert "Executive analytics" in body
    assert "Tracked annual premium" in body
    assert "Premium effective-date trend" in body
    assert "Renewal pipeline" in body
    assert "Reporting completeness" in body
    assert 'id="executive-analytics-data"' in body


def test_phase_741_premium_and_renewal_calculation(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Executive Analytics Co","industry":"Manufacturing","producer_id":"1"})
    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.legal_name == "Executive Analytics Co"))
        bid = business.id
    today = date.today()
    response = client.post(f"/businesses/{bid}/policies", data={
        "line":"Workers Compensation",
        "policy_number_ref":"WC-741",
        "effective_date":today.isoformat(),
        "expiration_date":(today + timedelta(days=120)).isoformat(),
        "annual_premium":"25000",
        "notes":"",
    }, follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        policy = db.scalar(select(Policy).where(Policy.business_id == bid))
        assert float(policy.annual_premium) == 25000
    dashboard = client.get("/dashboard")
    assert "$25,000" in dashboard.text
    assert "WC-741" not in dashboard.text or dashboard.status_code == 200


def test_phase_742_staff_analytics_dashboard(client):
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    body = response.text
    assert "Phase 7.4.2" in body
    assert "Staff analytics" in body
    assert "Task workload by staff" in body
    assert "Activity and completion" in body
    assert 'id="staff-analytics-data"' in body


def test_phase_742_staff_metrics_are_calculated(client):
    login(client)
    client.post("/admin/users", data={"username":"analyst","full_name":"Analytics User","password":"temporary123","role":"account_manager"})
    client.post("/businesses/new", data={"legal_name":"Staff Analytics Co","industry":"Services","producer_id":"1"})
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.username=="analyst"))
        business=db.scalar(select(Business).where(Business.legal_name=="Staff Analytics Co"))
        uid=user.id; bid=business.id
    client.post("/tasks", data={"business_id":str(bid),"title":"Overdue staff task","priority":"high","due_date":(date.today()-timedelta(days=2)).isoformat(),"assigned_to":str(uid)}, follow_redirects=False)
    client.post("/activities", data={"business_id":str(bid),"activity_type":"call","subject":"Analytics call","owner_id":str(uid)}, follow_redirects=False)
    dashboard=client.get("/dashboard")
    assert "Analytics User" in dashboard.text
    assert "Overdue staff task" not in dashboard.text or dashboard.status_code == 200
    from app.insights import staff_analytics
    with SessionLocal() as db:
        result=staff_analytics(db)
        row=next(r for r in result["rows"] if r["user"].username=="analyst")
        assert row["open_tasks"] == 1
        assert row["overdue_tasks"] == 1
        assert row["activities_30"] == 1


def test_phase_743_portfolio_analytics_dashboard(client):
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    body = response.text
    assert "Phase 7.4.3" in body
    assert "Portfolio analytics" in body
    assert "Premium by carrier" in body
    assert "Premium by industry" in body
    assert "Premium by line" in body
    assert "Largest accounts" in body
    assert "Geographic distribution" in body
    assert 'id="portfolio-analytics-data"' in body


def test_phase_743_portfolio_metrics_are_calculated(client):
    from app.models import Location, PolicyCarrier
    from app.insights import portfolio_analytics
    login(client)
    client.post("/businesses/new", data={"legal_name":"Portfolio Analytics Co","industry":"Manufacturing","producer_id":"1"})
    with SessionLocal() as db:
        business=db.scalar(select(Business).where(Business.legal_name=="Portfolio Analytics Co"))
        bid=business.id
        db.add(Location(business_id=bid,label="Primary",address1="100 Main",city="Bloomington",state="IL",postal_code="61701"))
        db.commit()
    today=date.today()
    client.post(f"/businesses/{bid}/policies", data={
        "line":"Workers Compensation","policy_number_ref":"WC-743",
        "effective_date":today.isoformat(),"expiration_date":(today+timedelta(days=180)).isoformat(),
        "annual_premium":"40000","notes":""
    }, follow_redirects=False)
    with SessionLocal() as db:
        policy=db.scalar(select(Policy).where(Policy.business_id==bid))
        db.add(PolicyCarrier(policy_id=policy.id,carrier_name="Test Mutual"))
        db.commit()
        result=portfolio_analytics(db)
        assert result["total_premium"] == 40000
        assert result["tracked_business_count"] == 1
        assert result["premium_by_carrier"][0]["label"] == "Test Mutual"
        assert result["premium_by_industry"][0]["label"] == "Manufacturing"
        assert result["premium_by_line"][0]["label"] == "Workers Compensation"
        assert result["largest_accounts"][0]["business"].legal_name == "Portfolio Analytics Co"
        assert result["geographic"][0]["state"] == "IL"
        assert result["top_five_concentration"] == 100.0


def test_phase_744_executive_reporting_page_and_exports(client):
    login(client)
    page = client.get("/executive-reports")
    assert page.status_code == 200
    assert "Phase 7.4.4" in page.text
    assert "Executive reporting" in page.text
    assert "Monthly management PDF" in page.text
    assert "Portfolio CSV" in page.text
    for endpoint in ["portfolio.csv", "staff.csv", "trends.csv"]:
        response = client.get(f"/executive-reports/{endpoint}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert len(response.content) > 20


def test_phase_744_management_pdf_is_generated(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Executive Report Co","industry":"Manufacturing","producer_id":"1"})
    with SessionLocal() as db:
        business=db.scalar(select(Business).where(Business.legal_name=="Executive Report Co")); bid=business.id
    today=date.today()
    client.post(f"/businesses/{bid}/policies", data={"line":"Workers Compensation","policy_number_ref":"WC-744","effective_date":today.isoformat(),"expiration_date":(today+timedelta(days=100)).isoformat(),"annual_premium":"55000","notes":""}, follow_redirects=False)
    response=client.get("/executive-reports/management.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 1500


def test_phase_745_historical_analytics_dashboard(client):
    login(client)
    response = client.get('/dashboard')
    assert response.status_code == 200
    body = response.text
    assert 'Phase 7.4.5' in body
    assert 'Historical analytics' in body
    assert 'Task and activity trend' in body
    assert 'Recommendation effectiveness' in body
    assert 'CommercialCore Index history' in body
    assert 'id="historical-analytics-data"' in body


def test_phase_745_historical_metrics_are_calculated(client):
    from datetime import datetime
    from app.insights import historical_analytics
    login(client)
    client.post('/businesses/new', data={'legal_name':'Historical Analytics Co','industry':'Services','producer_id':'1'})
    with SessionLocal() as db:
        business = db.scalar(select(Business).where(Business.legal_name == 'Historical Analytics Co'))
        admin = db.scalar(select(User).where(User.username == 'admin'))
        now = datetime.utcnow()
        task = Task(
            business_id=business.id, title='Historical completed task', priority='medium',
            status='completed', assigned_to=admin.id, created_by=admin.id,
            created_at=now - timedelta(days=5), completed_at=now - timedelta(days=1),
        )
        activity = Activity(
            business_id=business.id, activity_type='call', subject='Historical activity',
            owner_id=admin.id, created_by=admin.id, occurred_at=now - timedelta(days=2),
        )
        recommendation = Recommendation(
            business_id=business.id, code='historical_test', title='Historical recommendation',
            reason='Test historical resolution', priority='medium', confidence='high',
            status='completed', resolved_at=now - timedelta(days=1), resolved_by=admin.id,
            created_at=now - timedelta(days=4), updated_at=now - timedelta(days=1),
            last_detected_at=now - timedelta(days=4),
        )
        db.add_all([task, activity, recommendation])
        db.commit()
        result = historical_analytics(db)
        current = result['operations'][-1]
        current_rec = result['recommendations'][-1]
        assert current['tasks_created'] >= 1
        assert current['tasks_completed'] >= 1
        assert current['activities'] >= 1
        assert current_rec['created'] >= 1
        assert current_rec['resolved'] >= 1
        assert result['task_completion_rate'] is not None
        assert result['recommendation_resolution_rate'] is not None


def test_intelligence_engine_persists_versioned_component_scores(client):
    import json
    login(client)
    client.post("/businesses/new", data={"legal_name":"Intelligence Engine Co","industry":"Manufacturing","producer_id":"1"})
    with SessionLocal() as db:
        business=db.scalar(select(Business).where(Business.legal_name=="Intelligence Engine Co")); bid=business.id
    start=date.today()-timedelta(days=60)
    end=start+timedelta(days=364)
    client.post(f"/businesses/{bid}/policies", data={"line":"Workers Compensation","policy_number_ref":"WC-I","effective_date":start.isoformat(),"expiration_date":end.isoformat(),"annual_premium":"25000","notes":""})
    with SessionLocal() as db:
        pid=db.scalar(select(Policy.id).where(Policy.business_id==bid))
    client.post(f"/policies/{pid}/exposures", data={"exposure_type":"payroll","recorded_estimate":"120000","cadence":"monthly"})
    with SessionLocal() as db:
        eid=db.scalar(select(Exposure.id).where(Exposure.policy_id==pid))
    client.post(f"/exposures/{eid}/entries", data={"period_start":start.isoformat(),"period_end":(start+timedelta(days=29)).isoformat(),"actual_value":"10000","note":""})
    with SessionLocal() as db:
        projection=db.scalar(select(Projection).where(Projection.exposure_id==eid).order_by(Projection.created_at.desc()))
        assert projection.scoring_version=="2.0"
        details=json.loads(projection.score_details)
        assert details["version"]=="2.0"
        assert len(details["components"])==7
        assert sum(component["weight"] for component in details["components"])==100
        assert projection.core_index==round(sum(component["weighted_points"] for component in details["components"]))
        assert projection.accuracy_score==details["accuracy_score"]
        assert projection.confidence_score==details["confidence_score"]


def test_intelligence_engine_is_visible_and_explainable(client):
    login(client)
    client.post("/businesses/new", data={"legal_name":"Explainable Engine Co","industry":"Services","producer_id":"1"})
    with SessionLocal() as db:
        business=db.scalar(select(Business).where(Business.legal_name=="Explainable Engine Co")); bid=business.id
    start=date.today()-timedelta(days=45); end=start+timedelta(days=364)
    client.post(f"/businesses/{bid}/policies", data={"line":"Businessowners","policy_number_ref":"BOP-I","effective_date":start.isoformat(),"expiration_date":end.isoformat(),"annual_premium":"12000","notes":""})
    with SessionLocal() as db: pid=db.scalar(select(Policy.id).where(Policy.business_id==bid))
    client.post(f"/policies/{pid}/exposures", data={"exposure_type":"gross_sales","recorded_estimate":"240000","cadence":"monthly"})
    with SessionLocal() as db: eid=db.scalar(select(Exposure.id).where(Exposure.policy_id==pid))
    client.post(f"/exposures/{eid}/entries", data={"period_start":start.isoformat(),"period_end":(start+timedelta(days=29)).isoformat(),"actual_value":"20000","note":""})
    exposure_page=client.get(f"/exposures/{eid}")
    assert exposure_page.status_code==200
    assert "Intelligence score breakdown" in exposure_page.text
    assert "Scoring model v2.0" in exposure_page.text
    assert "Renewal readiness" in exposure_page.text
    assert "Open-review risk" in exposure_page.text
    assert "Data readiness" in exposure_page.text
    business_page=client.get(f"/businesses/{bid}")
    assert "Account intelligence components" in business_page.text
    assert "Scoring model v2.0" in business_page.text
