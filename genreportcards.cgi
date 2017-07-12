#!/usr/bin/perl

use strict;
use warnings;
no warnings 'uninitialized';

use DBI;
use Fcntl qw/:flock SEEK_END/;
use Image::Magick;
use Math::Round;
use POSIX;

#use PDF::API2;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root);
my $logd_in = 0;
my $id;
my $full_user = 0;

my %session;
my $update_session = 0;

my @grc_classes = ();

my $pdf_mode = 0;
my %grading = ();

my %core_fonts = (
"Times-Roman" => 1,
"Times-Bold" => 1,
"Times-Italic" => 1,
"Times-BoldItalic" => 1,

"Helvetica" => 1,
"Helvetica-Bold" => 1,

"Courier" => 1,
"Times-Bold" => 1,
"Courier-Oblique" => 1,
"Times-BoldOblique" => 1,

"Symbol" => 1,
"ZapfDingbats" => 1);

my ($page,$pdf,$filename) = (undef, undef, undef);
my ($llx,$urx, $lly, $ury) = (0,595,842,0);
my %data = ();
my $auto_resize = 1;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	#logged in 
	if (exists $session{"id"}) {
		$id = $session{"id"};
		#privileges set
		if (exists $session{"privileges"}) {
			my $priv_str = $session{"privileges"};
			my $spc = " ";
			$priv_str =~ s/\+/$spc/g;
			$priv_str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			if ($priv_str eq "all") { 
				$logd_in++;
				$full_user++;
			}
			else {
				if (exists $session{"token_expiry"} and $session{"token_expiry"} =~ /^\d+$/) {
					if ($session{"token_expiry"} > time) {
						$logd_in++;
						my @privs = split/,/,$priv_str;
						my $cntr = 0;
						foreach (@privs) {	
							if ($_ =~ m!^GRC\(([^\)]+)\)$!) {	
								push @grc_classes, $1;
							}
						}
					}
				}
			}
		}
	}
}

unless ($logd_in) {
	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /login.html?cont=/cgi-bin/genreportcards.cgi\r\n";
	print "Content-Type: text/html; charset=UTF-8\r\n";
   	my $res = 
qq{
<html>
<head>
<title>Spanj: Exam Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/genreportcards.cgi">/login.html?cont=/cgi-bin/genreportcards.cgi</a>. If you were not, <a href="/cgi-bin/genreportcards.cgi">Click Here</a> 
</body>
</html>
};

	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
	exit 0;
}

my $post_mode = 0;
my %auth_params;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	$post_mode++;
	my $str = "";

	while (<STDIN>) {
		$str .= $_;
	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;
	my @auth_req = split/&/,$str;
	for my $auth_req_line (@auth_req) {
		my $eqs = index($auth_req_line, "=");
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$auth_params{$k} = $v;
		}
	}
}

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/genreportcards.cgi">Generate Report Cards</a>
	<hr> 
};

my $con;
my $content = "";

if (@grc_classes or $full_user) {
	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
	#read some config information
	#exam,classes,subjects
	my $current_exam = "";
	my @valid_classes = ();
	my @valid_subjects = ();		
	#pre-load the blank grade, useful 
	#when get_grade returns a blank
	my %remarks = ("" => "");

	my %points = ();
	my %points_to_grade = ();

	my $principal = "";
	my %class_teachers = ();

	my $show_remarks = 0;
	my $show_pictures = 0;
	my $show_grade = 0;
	my $show_admission_data = 1;
	my $show_dorm = 0;
	my $show_input_by = 0;
	my $show_points = 0;
	my $show_subject_position = 0;
	my $grading_str = ""; 
	my $show_fees = 0;

	my $house_label = "House/Dorm";	
	my $position_graph = "line";
	my $mean_graph_label = "mark";
	my $mean_graph_plot_with = "line";

	my $report_card_footer = '';

	my $dp = 2;
	my $rank_partial = 1;
	my $currency = "KSh";

	my $auto_principals_remarks = 0;
	my %principals_remarks = ();

	my %rank_by_points = ();

	#I've considered replacing this SELECT clause with just 'SELECT id,value FROM vars'.
	#I choose to retain it this way in order to document the system variables recognized
	#by the report card tool.
	my $prep_stmt = $con->prepare("SELECT id,value FROM vars WHERE id='1-exam' OR id='1-classes' OR id='1-subjects' OR id='1-grading' OR id='1-remarks' OR id='1-show remarks' OR id='1-show pictures' OR id='1-show grade' OR id='1-show admission data' OR id='1-show dorm' OR id='1-show input by' OR id='1-show fees' OR id='1-points' OR id='1-show point average' OR id='1-show subject position' OR id='1-principal' OR id='1-decimal places' OR id='1-report card footer' OR id='1-rank partial' OR id='1-currency' OR id LIKE '1-class teacher%' OR id='1-house label' OR id='1-position graph' OR id='1-mean graph label' OR id='1-mean graph plot with' OR id='1-automatic principals remarks' OR id='1-principals remarks' OR id='1-rank by points'");

	if ($prep_stmt) {
		my $rc = $prep_stmt->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt->fetchrow_array()) {

				if ($rslts[0] eq "1-exam") {
					$current_exam = $rslts[1];
					my $current_year = (localtime)[5] + 1900;
					if ($current_exam !~ /$current_year/) {
						$current_exam .= "($current_year)";
					}
				}
				elsif ($rslts[0] eq "1-classes") {
					my $classes = $rslts[1];
					@valid_classes = split/,/,$classes;	
				}
				elsif ($rslts[0] eq "1-subjects") {
					my $subjects = $rslts[1];
					@valid_subjects = split/,/,$subjects;	
				}
				elsif ($rslts[0] eq "1-grading") {
					$grading_str = $rslts[1];
					my @grading_bts = split/,/,$grading_str;
					foreach (@grading_bts) {
						if ($_ =~ /^([^:]+):\s*(.+)$/) {
							my ($condition,$grade) = ($1,$2);
							#greater than (>|>=)
							#set min value
							if ($condition =~ /^\s*>\s*(\d+)$/) {
								${$grading{$grade}}{"min"} = $1
							}
							elsif ($condition =~ /^\s*>=\s*(\d+)$/) {
								my $min = $1;
								$min--;
								${$grading{$grade}}{"min"} = $min;
							}
							#less than (<|<=)
							#set max value of condition
							elsif ($condition =~ /^\s*<\s*(\d+)$/) {
								${$grading{$grade}}{"max"} = $1
							}
							elsif ($condition =~ /^\s*<=\s*(\d+)$/) {
								my $max = $1;
								$max++;
								${$grading{$grade}}{"max"} = $max;
							}
							#handle ranges
							#x-y
							elsif ($condition =~ /^\s*(\d+)\s*\-\s*(\d+)$/) {
								my ($min,$max) = ($1,$2);
								#don't be hard on users
								#reverse $min & $max if
								#they've been 'jumbled'
								if ($max < $min) {
									my $tmp = $max;
									$max = $min;
									$min = $tmp;
								}
								${$grading{$grade}}{"min"} = $min - 1;
								${$grading{$grade}}{"max"} = $max + 1;
							}
							#handle equality (=)
							#set eqs
							elsif ($condition =~ /^\s*=\s*(\d+)$/) {
								${$grading{$grade}}{"eq"} = $1
							}
						}
					}
				}
				elsif ($rslts[0] eq "1-remarks") {
					my $remarks_str = $rslts[1];
					my @remarks_bts = split/,/,$remarks_str;
					foreach (@remarks_bts) {
						if ($_ =~ /^([^:]+):\s*(.+)/) {
							my ($grade,$remark) = ($1,$2);
							$remarks{$grade} = $remark;	
						}
					}
				}

				elsif ($rslts[0] eq "1-points") {
					my $points_str = $rslts[1];
					my @points_bts = split/,/,$points_str;
					foreach (@points_bts) {
						if ($_ =~ /^([^:]+):\s*(.+)/) {
							my ($grade,$point_s) = ($1,$2);
							$points{$grade} = $point_s;
							$points_to_grade{$point_s} = $grade;
						}
					}
				}

				elsif ($rslts[0] eq "1-show remarks") {
					if (lc($rslts[1]) eq "yes") {
						$show_remarks = 1;
					}
				}

				elsif ($rslts[0] eq "1-show grade") {
					if (lc($rslts[1]) eq "yes") {
						$show_grade = 1;
					}
				}


				elsif ($rslts[0] eq "1-show dorm") {
					if (lc($rslts[1]) eq "yes") {
						$show_dorm = 1;
					}
				}

				elsif ($rslts[0] eq "1-show pictures") {
					if (lc($rslts[1]) eq "yes") {
						$show_pictures = 1;
					}
				}

				elsif ($rslts[0] eq "1-show admission data") {
					if (lc($rslts[1]) eq "no") {
						$show_admission_data = 0;
					}
				}

				elsif ($rslts[0] eq "1-show input by") {
					if (lc($rslts[1]) eq "yes") {
						$show_input_by = 1;
					}
				}

				elsif ($rslts[0] eq "1-show point average") {
					if (lc($rslts[1]) eq "yes") {
						$show_points = 1;
					}
				}

				elsif ($rslts[0] eq "1-show subject position") {
					if (lc($rslts[1]) eq "yes") {
						$show_subject_position = 1;
					}
				}

				elsif ($rslts[0] eq "1-show fees") {
					if (lc($rslts[1]) eq "yes") {
						$show_fees = 1;
					}
				}

				elsif ($rslts[0] eq "1-principal") {
					$principal = $rslts[1];
				}

				elsif ($rslts[0] eq "1-report card footer") {
					$report_card_footer = htmlspecialchars($rslts[1]);
				}

				elsif ($rslts[0] eq "1-currency") {
					$currency = $rslts[1];
				}

				elsif ($rslts[0] =~ /^1-class\steacher\s([^\(]+)\((\d{4,})\)$/) {
					my $class = $1;
					my $year = $2;

					my $class_yr = 1;
					if ($class =~ /(\d+)/) {
						$class_yr = $1; 
					}

					my $current_year = (localtime)[5] + 1900;

					my $class_now = ($current_year - $year) + $class_yr; 
					$class =~ s/\d+/$class_now/;

					$class_teachers{lc($class)} = $rslts[1];
				}
				elsif ($rslts[0] eq "1-decimal places") {
					if ( $rslts[1] =~ /^[0-9]$/ ) {
						$dp = $rslts[1];
					}
				}

				elsif ($rslts[0] eq "1-rank partial") {
					if (defined $rslts[1] and lc($rslts[1]) eq "no") {
						$rank_partial = 0;
					}
				}

				elsif ($rslts[0] eq "1-house label") {
					if ( defined $rslts[1] ) {
						$house_label = htmlspecialchars($rslts[1]);
					}
				}

				elsif ($rslts[0] eq "1-position graph") {
					if ( defined $rslts[1]) {
						$position_graph = $rslts[1];
					}
				}

				elsif ($rslts[0] eq "1-mean graph label") {
					if ( defined $rslts[1]) {
						$mean_graph_label = $rslts[1];
					}
				}

				elsif ( $rslts[0] eq "1-mean graph plot with" ) {
					if ( defined $rslts[1] ) {
						$mean_graph_plot_with = $rslts[1];
					}
				}

				#automatic principal's remarks
				elsif ( $rslts[0] eq "1-automatic principals remarks" ) {

					if (defined $rslts[1] and lc($rslts[1]) eq "yes") {	
						$auto_principals_remarks = 1;
					}
				}

				elsif ( $rslts[0] eq "1-principals remarks" ) {

					my $remarks_str = $rslts[1];
					my @remarks_bts = split/,/,$remarks_str;
					foreach (@remarks_bts) {
						if ($_ =~ /^([^:]+):\s*(.+)/) {
							my ($grade,$remark) = ($1,$2);
							$principals_remarks{$grade} = $remark;	
						}
					}

				}

				elsif ( $rslts[0] eq "1-rank by points" ) {

					if ( defined($rslts[1]) and $rslts[1] =~ /^(?:[0-9]+,?)+$/ ) {
						my @yrs = split/,/,$rslts[1];
						for my $yr (@yrs) {
							$rank_by_points{$yr}++;
						}
					}
				}

			}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars statement: ", $prep_stmt->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt->errstr, $/;
	}

	if ($auto_principals_remarks) {
		#same remark as 'remarks' unless customized
		unless(keys %principals_remarks) {
			%principals_remarks = %remarks;
		}
	}

	if (keys %grading) {
		$show_grade++;
	}

	my @authd_classes = ();

	if ($full_user) {
		@authd_classes = @valid_classes;
	}

	else {
		#why did I not just @authd_classes = @grc_classes?
		#well, I'm paranoid: I don't trust @grc_classes
		#plus, I want to get the case right so future REs don't
		#have to be /i modified
		for my $valid_class (@valid_classes) {
			A: for my $grc_class (@grc_classes) {
				if ( lc($valid_class) eq lc($grc_class) ) {
					push @authd_classes, $valid_class;
					last A;
				}
			}
		}
	}

	if ($post_mode) {
		#check confirm code
		if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"}) {
			
			#verify authority to edit this class
			my $fail = 0;
			my $err_str = "";

			my $exam = undef; 
			my %included_exams = ();
			my %included_exams_age = ();

			if (exists $auth_params{"exam"}) { 
				$exam = $auth_params{"exam"};
			}
			else {
				$fail = 1;
				$err_str = "Sorry you did not select any exam.";
			}
			my %classes;
	
			my $cntr = 0;
			my $inc_cnt = 0;

			B: foreach (keys %auth_params) {
				if ($_ =~ /^class_/) {
					my $class = $auth_params{$_};
					my $match = 0;
					C: foreach (@authd_classes) {
						if (lc($_) eq lc($class)) {
							$class = $_;
							$match++;
							last C;
						}
					}
					unless ($match) {
						$fail = 1;
						$err_str = "Sorry, you are not authorized to edit one or more of the classes selected.";
						last B;
					}
					$classes{lc($class)}++;
					$cntr++;
				}
	
				elsif ($_ =~ /^include_\d+$/) {	
					my $included_exam = $auth_params{$_};
					if ($included_exam ne $exam) {
						$included_exams{$included_exam}++;
						$included_exams_age{$included_exam} = ++$inc_cnt;
					}
				}
			}

			if ($cntr == 0) {
				$fail = 1;
				$err_str = "Sorry, you did not select any class.";	
			}
			if ($fail) {
				$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<em>$err_str</em>
</body>
</html>
};
			}
			else {

				my $start_yr = undef;
				my $grad_yr = undef;

				#valid request- OK confirmation code, authorized class
				my %possib_start_yrs = ();

				my $current_year = (localtime)[5] + 1900;
				if ($exam =~ /\D*(\d{4,})\D*/) {
					$current_year = $1;
				}

				for my $class_name (keys %classes) {	
					my ($class_year,$start_year) = (-1,-1);
					if ($class_name =~ /(\d+)/) {
						$class_year = $1;	
						$start_year = 1 + ($current_year - $class_year);
						$possib_start_yrs{$start_year}++;
					}
				}

				my %stud_rolls;
				my $matched_rolls = 0;

				my @start_yr_where_clause_bts = ();

				foreach (keys %possib_start_yrs) {
					push @start_yr_where_clause_bts, "start_year=?";
				}

				my $start_yr_where_clause = join (' OR ', @start_yr_where_clause_bts);

				my $prep_stmt3 = $con->prepare("SELECT table_name,class,grad_year,size,start_year FROM student_rolls WHERE $start_yr_where_clause");
				if ($prep_stmt3) {
					my $rc = $prep_stmt3->execute(keys %possib_start_yrs);
					if ($rc) {
						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							my $class_yr_then = 1 + ($current_year - $rslts[4]);
							$rslts[1] =~ s/\d+/$class_yr_then/;
							$stud_rolls{$rslts[0]} = {"class" => $rslts[1], "grad_year" => $rslts[2], "size" => $rslts[3]};
							$matched_rolls++;

							$start_yr = $rslts[4];
							$grad_yr = $rslts[2];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt3->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt3->errstr, $/;
				}

				if ($matched_rolls) {
					my @where_clause_bts = ();
					foreach (keys %stud_rolls) {
						push @where_clause_bts, "roll=?";
					}
					my $where_clause = join(' OR ', @where_clause_bts);

					my %marksheet_list;
					my %all_exams = ();

			      		my $prep_stmt4 = $con->prepare("SELECT table_name,roll,exam_name,subject,time FROM marksheets WHERE $where_clause");
					if ($prep_stmt4) {

						my @exec_params = keys %stud_rolls;
						#unshift @exec_params,$exam,keys %included_exams;

						my $rc = $prep_stmt4->execute(@exec_params);
						if ($rc) {
							while (my @rslts = $prep_stmt4->fetchrow_array()) {

								if ( not exists $all_exams{$rslts[2]} or $all_exams{$rslts[2]} < $rslts[4] ) {
									$all_exams{$rslts[2]} = $rslts[4];
								}

								${$stud_rolls{$rslts[1]}}{"marksheet_" . $rslts[2] . "_" . $rslts[3]} = $rslts[0];
								if (keys %included_exams) {
									if (exists $included_exams_age{$rslts[2]}) {
										if ($rslts[4] > $included_exams_age{$rslts[2]}) {
											$included_exams_age{$rslts[2]} = $rslts[4];
										}
									}
								}
								$marksheet_list{$rslts[0]} = $rslts[2] . "_" . $rslts[3];	
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt4->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt4->errstr, $/;
					}

					#replace use of edit_marksheet_log with
					#use of teachers;
					#may need to remove all refs to edit_marksheet_log
					my %teachers;
		
						
					my $prep_stmt6 = $con->prepare("SELECT name,subjects,id FROM teachers");
						
					if ($prep_stmt6) {
						my $rc = $prep_stmt6->execute();
						if ($rc) {

							my $current_year = (localtime)[5] + 1900;

							my $yrs_study = 4;
							if (@valid_classes) {
								my $oldest = -1;
								
								for my $class (@valid_classes) {
									if ($class =~ /(\d+)/) {
										my $yr = $1;
										$oldest = $yr if ($yr > $oldest);
									}
								}
								$yrs_study = $oldest;
							}

							while (my @rslts = $prep_stmt6->fetchrow_array()) {
								my $name  = $rslts[0];
								my $subjs = $rslts[1];
	
								my @subjs_bts = split/;/, $subjs;
								for my $subj_bt (@subjs_bts) {
									
									if ($subj_bt =~ /^([^\[]+)\[([^\]]+)\]$/) {
										my $subj = $1;
										my $classes_str = $2;

										my @classes = split/,/,$classes_str;
										
										for my $class (@classes) {
											#print "X-Debug-$rslts[2]: $name => $subj ::: $class\r\n";

											if ($class =~ /^([^\(]+)\(([^\)]+)\)$/) {
												my $stream = $1;
												my $end_yr = $2;
					
												my $form_yr_now = $current_year - ($end_yr - $yrs_study);
									
												$stream =~ s/\d+/$form_yr_now/;
												$teachers{lc($subj."_" . $stream)} = $name;
											}
										}
									}
								}
							}

						}
						else {
							print STDERR "Could not execute SELECT FROM teachers: ", $prep_stmt6->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM teachers: ", $prep_stmt6->errstr, $/;
					}
					

					my $cnt = 0;
					foreach (keys %teachers) {
						#print "X-Debug-$cnt: $_-> $teachers{$_}\r\n";
						$cnt++;
					}
					$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
};

					my %subject_class_sizes;

					#read student rolls
					#save adm,marks at admission & subjects
					my %student_data;
	
					my %all_exams_mean_scores = ();
					my %all_exams_ranks = ();

					for my $roll (keys %stud_rolls) {

						my $class = ${$stud_rolls{$roll}}{"class"};

						my $prep_stmt5 = $con->prepare("SELECT adm,s_name,o_names,marks_at_adm,subjects,clubs_societies,sports_games,responsibilities,house_dorm FROM `$roll`");
						if ($prep_stmt5) {

							my $rc = $prep_stmt5->execute();
							if ($rc) {
								while (my @rslts = $prep_stmt5->fetchrow_array()) {
									my ($adm,$s_name,$o_names,$marks_at_adm,$subjects,$clubs_societies,$sports_games,$responsibilities,$house_dorm) = @rslts;
									if (not defined($marks_at_adm) or $marks_at_adm eq "") {
										$marks_at_adm = -1;
									}
									 
									$student_data{$adm} = 
									{
									"name" => $s_name . " " . $o_names,
									"marks_at_adm" => $marks_at_adm,
									"list_subjects" => $subjects,
									"roll" => $roll,
									"total" => 0,
									"subject_count" => 0,
									"avg" => -1,
									"admission_rank" => "N/A",
									"class_rank" => 1,
									"overall_rank" => 1,
									"class" => $class,
									"clubs_societies" => $clubs_societies,
									"sports_games" => $sports_games,
									"responsibilities" => $responsibilities,
									"house_dorm" => $house_dorm,
									"arrears" => "N/A",
									"next_term_fees" => "N/A"
									};

									#preset the values of subjects to N/A
									my @subjects_list = split/,/, $subjects;
									my $subjects_count = scalar(@subjects_list);

									foreach ( @subjects_list ) {
										#subjects lookup
										$student_data{$adm}->{"subject_lookup"}->{$_}++;
										
									}


									for my $exam_n ($exam, keys %included_exams) {

										${$student_data{$adm}}{"subject_count_${exam_n}"} = 0;	

										#if not doing partial rank; fix number subjects
										#if ( $exam_n eq $exam ) {

											unless ( $rank_partial ) { 
												${$student_data{$adm}}{"subject_count_${exam_n}"} = $subjects_count;	
											}
										#}

										${$student_data{$adm}}{"total_marks_${exam_n}"} = 0;
										${$student_data{$adm}}{"total_points_${exam_n}"} = 0;
										${$student_data{$adm}}{"mean_score_${exam_n}"} = -1;
										${$student_data{$adm}}{"mean_points_${exam_n}"} = -1;
										${$student_data{$adm}}{"class_rank_${exam_n}"} = 1;
										${$student_data{$adm}}{"overall_rank_${exam_n}"} = 1;

										foreach (@subjects_list) {
											#don't double count students taking a given subject--
											#only update this value for 1 exam
											if ($exam_n eq $exam) {
												$subject_class_sizes{$_}++;
											}

											${$student_data{$adm}}{"subject_${exam_n}_${_}"} = -1;
											${$student_data{$adm}}{"position_subject_${exam_n}_${_}"} = -1;
										}
									}	
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM $roll statement: ", $prep_stmt5->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt5->errstr, $/;
						}
					}
				
					#read fee arrears
					if ($show_fees) {

						my $prep_stmt7 = $con->prepare("SELECT adm,arrears,next_term_fees FROM `fee_arrears`");

						if ($prep_stmt7) {
							my $rc = $prep_stmt7->execute();
							if ($rc) {

								while ( my @rslts = $prep_stmt7->fetchrow_array() ) {
									#filter out the students of interest
									if ( exists $student_data{$rslts[0]} ) {
										${$student_data{$rslts[0]}}{"arrears"} = $rslts[1]; 
										${$student_data{$rslts[0]}}{"next_term_fees"} = $rslts[2]; 
									}
								}
							}

						}
						else {
							print STDERR "Could not prepare SELECT FROM `fee_arrears`: ", $prep_stmt7->errstr, $/;
						}

					}
					

					#read the marksheets in DB:-
					#for each marksheet, update student_data	
					#in the switch from F2-F3 the student's, for instance,
					#'subjects' records are changed
					#RULE: assume subjects can be removed but not
					#added. Therefore, any missing records in the 
					#{"subjects"} field are N/A
					#any additional values however, are allowed
						
					for my $stud_roll (keys %stud_rolls) {
						my %recs = %{$stud_rolls{$stud_roll}};		
						for my $rec_key (keys %recs) {
							my $prep_stmt5;
							if ($rec_key =~ /^marksheet_([^_]+)_(.+)$/) {

								my $n_exam = $1;
								my $subject = $2;

								my $marksheet = $recs{$rec_key};
								
								$prep_stmt5 = $con->prepare("SELECT adm,marks FROM `$marksheet`");

								my %marksheet_data = ();

								if ($prep_stmt5) {
								
									my $rc = $prep_stmt5->execute();
									if ($rc) {
										while (my @rslts = $prep_stmt5->fetchrow_array()) {
											$marksheet_data{$rslts[0]} = $rslts[1];
										}
									}
									else {
										print STDERR "Could not execute SELECT FROM $marksheet statement: ", $prep_stmt5->errstr, $/;
									}
								}
								else {
									print STDERR "Could not prepare SELECT FROM marksheet statement: ", $prep_stmt5->errstr, $/;
								}
								for my $stud_adm (keys %marksheet_data) {
									my $score = $marksheet_data{$stud_adm};
									my $point_s = $points{get_grade($score)}; 

									#update all_exams_mean_scores
									if ( $rank_partial or not exists $student_data{$stud_adm}->{"subject_lookup"}->{$subject} ) {
										${$all_exams_mean_scores{$stud_adm}}{"count_$n_exam"}++;
									}
									else {
										${$all_exams_mean_scores{$stud_adm}}{"count_$n_exam"} = ${$student_data{$stud_adm}}{"subject_count_${exam}"};
									}

									${$all_exams_mean_scores{$stud_adm}}{"total_$n_exam"} += $score;
									${$all_exams_mean_scores{$stud_adm}}{"points_total_$n_exam"} += $point_s;

									${$all_exams_mean_scores{$stud_adm}}{"mean_score_$n_exam"} = ${$all_exams_mean_scores{$stud_adm}}{"total_$n_exam"} / ${$all_exams_mean_scores{$stud_adm}}{"count_$n_exam"} unless ( ${$all_exams_mean_scores{$stud_adm}}{"count_$n_exam"} == 0);

									${$all_exams_mean_scores{$stud_adm}}{"mean_points_$n_exam"} = ${$all_exams_mean_scores{$stud_adm}}{"points_total_$n_exam"} / ${$all_exams_mean_scores{$stud_adm}}{"count_$n_exam"} unless ( ${$all_exams_mean_scores{$stud_adm}}{"count_$n_exam"} == 0);									

									#jump along unless exam is one of
									#those of utmost importance right now
									next unless ($n_exam eq $exam or (exists $included_exams{$n_exam}));

									#only increment if doing partial rank or this subject was dropped 
									#if ($n_exam eq $exam) {
										if ( $rank_partial or not exists $student_data{$stud_adm}->{"subject_lookup"}->{$subject} ) {
											${$student_data{$stud_adm}}{"subject_count_${n_exam}"}++;
										}
									#}

									${$student_data{$stud_adm}}{"total_marks_${n_exam}"} += $score;
									${$student_data{$stud_adm}}{"total_points_${n_exam}"} += $point_s;

									${$student_data{$stud_adm}}{"mean_score_${n_exam}"} = ${$student_data{$stud_adm}}{"total_marks_${n_exam}"} / ${$student_data{$stud_adm}}{"subject_count_${n_exam}"} unless (${$student_data{$stud_adm}}{"subject_count_${n_exam}"} == 0);

									${$student_data{$stud_adm}}{"mean_points_${n_exam}"} = ${$student_data{$stud_adm}}{"total_points_${n_exam}"} / ${$student_data{$stud_adm}}{"subject_count_${n_exam}"} unless (${$student_data{$stud_adm}}{"subject_count_${n_exam}"} == 0);
									
 									${$student_data{$stud_adm}}{"subject_${n_exam}_${subject}"} = $marksheet_data{$stud_adm};
									#${$student_data{$stud_adm}}{"subject_count_${n_exam}"}++;
									#${$student_data{$stud_adm}}{"total_${n_exam}"} += $marksheet_data{$stud_adm};	
									#${$student_data{$stud_adm}}{"avg_${n_exam}"} = ${$student_data{$stud_adm}}{"total_${n_exam}"} / ${$student_data{$stud_adm}}{"subject_count_${n_exam}"} unless (${$student_data{$stud_adm}}{"subject_count_${n_exam}"} == 0);

								}
							}
						}
					}
						
					#rank students
					#simple strategy: do a sort, use a cntr to keep track of 
					#ranks. 1 cntr tracks the overall rank, (a hash of => others)
					#tracks the rank for each class
					#to deal with 

					my %means = ();

					#determine overall rank
					#all this code can probably be replaced
					#with a  neat subroutine
					#TODO	
					for my $exam_n_1 ($exam, keys %included_exams) {

						my %class_rank_cntr = ();
						foreach (keys %stud_rolls) {
							my $class = ${$stud_rolls{$_}}{"class"};
							$class_rank_cntr{$class} = 0;
						}
						my $overall_cntr = 0;

						my $rank_by = "mean_score";
						
						my $exam_yr = $current_year;

						if ( exists $included_exams_age{$exam_n_1} ) {
							$exam_yr = (localtime $included_exams_age{$exam_n_1} )[5] + 1900;
						}

						my $yr_study = ($exam_yr - $start_yr) + 1;

						if ( exists $rank_by_points{$yr_study} ) {
							$rank_by = "mean_points";
						}

						#print "X-Debug: exam_yr-> $exam_yr; start year-> $start_yr; yr_study-> $yr_study\r\n";

						#my $seq_cntr = 0;

						for my $stud ( sort {${$student_data{$b}}{"${rank_by}_${exam_n_1}"} <=> ${$student_data{$a}}{"${rank_by}_${exam_n_1}"} } keys %student_data ) {

							${$student_data{$stud}}{"overall_rank_${exam_n_1}"} = ++$overall_cntr;
				
							#my $f_seq_cntr = sprintf("%03d", $seq_cntr++);
							#print qq!X-Debug-seq-$f_seq_cntr: ${$student_data{$stud}}{"${rank_by}_${exam_n_1}"} -> ${$student_data{$stud}}{"overall_rank_${exam_n_1}"}\r\n! if ($exam_n_1 eq $exam);

							#print qq!X-Debug-$overall_cntr: adm->$stud; mark->${$student_data{$stud}}{"${rank_by}_${exam_n_1}"}\r\n!;

							my $class = ${$student_data{$stud}}{"class"}; 
							${$student_data{$stud}}{"class_rank_${exam_n_1}"} = ++$class_rank_cntr{$class};
						}

					}


					#all exams ranks - for progress plot
					for my $exam_n_4 ( keys %all_exams ) {

						my $rank_by = "mean_score";

						my $exam_yr = $current_year;

						if ( exists $all_exams{$exam_n_4} ) {
							$exam_yr = ( localtime $all_exams{$exam_n_4} )[5] + 1900;
						}
					
						my $yr_study = ($exam_yr - $start_yr) + 1;

						if ( exists $rank_by_points{$yr_study} ) {
							$rank_by = "mean_points";
						}

						my $overall_cntr = 0;
						for my $stud ( sort {${$all_exams_mean_scores{$b}}{"${rank_by}_${exam_n_4}"} <=> ${$all_exams_mean_scores{$a}}{"${rank_by}_${exam_n_4}"} } keys %all_exams_mean_scores ) {
							${$all_exams_ranks{$stud}}{$exam_n_4} = ++$overall_cntr;
						}

						my $prev_rank = -1;
						my $prev_avg = -1;
						my $seq_cntr = 0;

						#deal with ties in overall_rank
						for my $stud_2 ( sort { ${$all_exams_ranks{$a}}{$exam_n_4} <=> ${$all_exams_ranks{$b}}{$exam_n_4} } keys %all_exams_ranks ) {
							my $current_rank = ${$all_exams_ranks{$stud_2}}{$exam_n_4};
							my $current_avg = ${$all_exams_mean_scores{$stud_2}}{"${rank_by}_${exam_n_4}"};

							#my $f_seq_cntr = sprintf("%03d", $seq_cntr++);
							#print "X-Debug-seq-$f_seq_cntr: $current_rank\r\n"  if ($exam_n_4 eq $exam);
							#
							#my $f_rank = sprintf("%03d", $current_rank);
							#print "X-Debug-$f_rank: $exam_n_4 -> (Curr rank->$current_rank, Curr avg->$current_avg, Prev avg->$prev_avg)\r\n" if ($exam_n_4 eq $exam);

							#if ($prev_rank >= 0) {
								#tie
								if ($prev_avg == $current_avg) {
									${$all_exams_ranks{$stud_2}}{$exam_n_4} = $prev_rank;	
								}
							#}
							$prev_rank = ${$all_exams_ranks{$stud_2}}{$exam_n_4};
							$prev_avg  = $current_avg;
						}
					}

					#subject ranks
					for my $exam_n_2 ($exam, keys %included_exams) {
						for my $subject (@valid_subjects) {
							my $subj_rank_cntr = 0;
							for my $stud (sort {${$student_data{$b}}{"subject_${exam_n_2}_${subject}"} <=> ${$student_data{$a}}{"subject_${exam_n_2}_${subject}"} } keys %student_data) {
								${$student_data{$stud}}{"position_subject_${exam_n_2}_${subject}"} = ++$subj_rank_cntr;
							}
						}

						#handle ties
						for my $subject_2 (@valid_subjects) {
							my $prev_rank = -1;
							my $prev_mark = -1;
							for my $stud_2 (sort { ${$student_data{$a}}{"position_subject_${exam_n_2}_${subject_2}"} <=> ${$student_data{$b}}{"position_subject_${exam_n_2}_${subject_2}"} } keys %student_data) {
								my $current_rank = ${$student_data{$stud_2}}{"position_subject_${exam_n_2}_${subject_2}"};
								my $current_mark = ${$student_data{$stud_2}}{"subject_${exam_n_2}_${subject_2}"};

								#if ($prev_rank >= 0) {
									#tie
									if ($prev_mark == $current_mark) {
										${$student_data{$stud_2}}{"position_subject_${exam_n_2}_${subject_2}"} = $prev_rank;	
									}
								#}
								$prev_rank = ${$student_data{$stud_2}}{"position_subject_${exam_n_2}_${subject_2}"};
								$prev_mark  = $current_mark;
							}
						}
					}
					
					
					for my $exam_n_3 ($exam, keys %included_exams) {

						my $rank_by = "mean_score";
						my $exam_yr = $current_year;

						if ( exists $included_exams_age{$exam_n_3} ) {
							$exam_yr = (localtime $included_exams_age{$exam_n_3} )[5] + 1900;
						}

						my $yr_study = ($exam_yr - $start_yr) + 1;

						if ( exists $rank_by_points{$yr_study} ) {
							$rank_by = "mean_points";
						}

						my $prev_rank = -1;
						my $prev_avg = -1;

						#my $seq_cntr = 0;
						#deal with ties in overall_rank
						for my $stud_2 (sort { ${$student_data{$a}}{"overall_rank_${exam_n_3}"} <=> ${$student_data{$b}}{"overall_rank_${exam_n_3}"} } keys %student_data) {

							my $current_rank = ${$student_data{$stud_2}}{"overall_rank_${exam_n_3}"};
							my $current_avg =  ${$student_data{$stud_2}}{"${rank_by}_${exam_n_3}"};

							#my $f_rank = sprintf("%03d", $current_rank);
							#print "X-Debug-$f_rank-$stud_2: $exam_n_3 -> (Curr rank->$current_rank, Curr avg->$current_avg, Prev avg->$prev_avg)\r\n" if ($exam_n_3 eq $exam);
							#my $f_seq_cntr = sprintf("%03d", $seq_cntr++);
							#print "X-Debug-seq-$f_seq_cntr: $current_rank\r\n"  if ($exam_n_3 eq $exam);

							#if ($prev_rank >= 0) {
								#tie
								if ($prev_avg == $current_avg) {
									#print "X-Debug-$f_seq_cntr: tie(Curr rank->$current_rank, Curr avg->$current_avg; Prev avg->$prev_avg)\r\n";
									${$student_data{$stud_2}}{"overall_rank_${exam_n_3}"} = $prev_rank;	
								}
							#}
							$prev_rank = ${$student_data{$stud_2}}{"overall_rank_${exam_n_3}"};
							$prev_avg  = $current_avg;
						}


						#handle ties in class_rank 
						my %class_rank_cursor = ();
	
						foreach (keys %stud_rolls) {
							my $class = ${$stud_rolls{$_}}{"class"};
							$class_rank_cursor{$class} = {"prev_rank" => -1, "prev_avg" => -1};
						}

						my $prev_overall_rank = -1;

						#already taken care of ties in overall rank, use that
						#to determine if there's a tie
						for my $stud_3 ( sort {${$student_data{$b}}{"${rank_by}_${exam_n_3}"} <=> ${$student_data{$a}}{"${rank_by}_${exam_n_3}"} } keys %student_data ) {
							my $class = ${$student_data{$stud_3}}{"class"};
				
							my $current_rank = ${$student_data{$stud_3}}{"class_rank_${exam_n_3}"};
							my $current_avg = ${$student_data{$stud_3}}{"${rank_by}_${exam_n_3}"};
							
							#if (${$class_rank_cursor{$class}}{"prev_rank"} >= 0) {
								#tie
								if (${$class_rank_cursor{$class}}{"prev_avg"} == $current_avg) {
								#if ( ${$student_data{$stud_3}}{"overall_rank"} == $prev_overall_rank ) {
									${$student_data{$stud_3}}{"class_rank_${exam_n_3}"} = ${$class_rank_cursor{$class}}{"prev_rank"} unless ( ${$class_rank_cursor{$class}}{"prev_rank"} == -1) ;
								}
							#}
							${$class_rank_cursor{$class}}{"prev_rank"} = ${$student_data{$stud_3}}{"class_rank_${exam_n_3}"};
							${$class_rank_cursor{$class}}{"prev_avg"}  = $current_avg;

							$prev_overall_rank = ${$student_data{$stud_3}}{"overall_rank"};
						}

					}
					#determine adm_ranks
					my $adm_rank = 0;

					for my $stud_4 (sort { ${$student_data{$b}}{"marks_at_adm"} <=> ${$student_data{$a}}{"marks_at_adm"} } keys %student_data) {
						#students with no 'marks at admission' will have a rank of 'N/A'
						if (${$student_data{$stud_4}}{"marks_at_adm"} >= 0) {
							${$student_data{$stud_4}}{"admission_rank"} = ++$adm_rank;
						}
					}

					#deal with ties
					my $prev_rank = -1;
					my $prev_marks_at_adm = -1;
						
					for my $stud_5 (sort { ${$student_data{$a}}{"admission_rank"} <=> ${$student_data{$b}}{"admission_rank"} } keys %student_data) {
						my $current_rank = ${$student_data{$stud_5}}{"admission_rank"};
						my $current_marks_at_adm = ${$student_data{$stud_5}}{"marks_at_adm"};

						#if ($prev_rank >= 0) {
							#tie
							if ($prev_marks_at_adm == $current_marks_at_adm) {
								${$student_data{$stud_5}}{"admission_rank"} = $prev_rank;	
							}
						#}
						$prev_rank = ${$student_data{$stud_5}}{"admission_rank"};
						$prev_marks_at_adm  = $current_marks_at_adm;
					}

					my %years_of_study = ();

					#generate progress graphs
				for my $stud_8 (keys %all_exams_mean_scores) {

					next if (not exists $classes{lc(${$student_data{$stud_8}}{"class"})});	

					#add mean score
					my ($min_rank, $max_rank, $min_mean, $max_mean) = (undef, undef, undef, undef);
					my (@exam_list, @overall_rank, @mean_score);

					for my $exam_n_5 (sort { $all_exams{$a} <=> $all_exams{$b} } keys %all_exams) {

						next unless (exists ${$all_exams_mean_scores{$stud_8}}{"mean_score_$exam_n_5"});

						push @exam_list, qq!"$exam_n_5"!;
						my ($overall_rank, $mean_score) = (${$all_exams_ranks{$stud_8}}{$exam_n_5}, ${$all_exams_mean_scores{$stud_8}}{"mean_score_$exam_n_5"}); 

						push @overall_rank,$overall_rank;
						push @mean_score, $mean_score;

						#set the min and max ranks as the 1st
						#values of class and overall ranks seen (respectively)
						if ( not defined($min_rank) ) {
							$min_rank = $max_rank = $overall_rank;	
						}
						else {
							$max_rank = $overall_rank if ($overall_rank > $max_rank);
							$min_rank = $overall_rank if ($overall_rank < $min_rank);
						}

						#set the min and max means as the 1st
						#mean score seen
						if ( not defined($min_mean) ) {
							$min_mean = $max_mean = int($mean_score);
						}
	
						else {
							$max_mean = int($mean_score) if ($mean_score > $max_mean);
							$min_mean = int($mean_score) if ($mean_score < $min_mean);
						}
					}

			
				
					$min_rank = 1 if ($min_rank < 1);		
					$min_mean = 0 if ($min_mean < 0);
				
					my $last_exam_index = scalar(@exam_list) - 1;

					if (scalar(@overall_rank) > 0 and scalar(@mean_score) > 0) {
						my $mean_gnuplot_data = "";
						my $position_overall_gnuplot_data = "";

						my @xtics = ();
						my $current_year = "";
						for (my $i = 0; $i < @exam_list; $i++) {

							$mean_gnuplot_data .= "$i $mean_score[$i]\n";
							$position_overall_gnuplot_data .= "$i $overall_rank[$i]\n";
							
							if ($exam_list[$i] =~ /(\d{4})/) {
								my $yr = $1;
								#add to xtics
								if ($yr ne $current_year) {
									push @xtics, qq%'$yr' $i%;
									$current_year = $yr;
								}
								else {
									push @xtics, qq%'' $i%;
								}
							}
						}

						$mean_gnuplot_data .= "e\n";
						$position_overall_gnuplot_data .= "e\n";	

						my $set_x_tics = "";
						if (@xtics) {
							$set_x_tics = "set xtics (" . join(", ", @xtics) . ");\\";
						}

							
						my $incr_mean_plot = ($max_mean - $min_mean)/6;

						$incr_mean_plot = 1 if ($incr_mean_plot < 1);
						$incr_mean_plot = int($incr_mean_plot) + 1;

						my $set_y_tics = "set ytics $min_mean,$incr_mean_plot,$max_mean;\\";

						if ($mean_graph_label eq "grade") {

							$set_y_tics = "";

							my @ytics = ();
							my $prev_tic_grade = "";	

							for (my $i = $min_mean; $i <= $max_mean; $i += $incr_mean_plot) {

								my $tic_label = $i;
								my $tic_grade = get_grade($i);
								
								unless ( $tic_grade eq $prev_tic_grade ) {
									$tic_label .= "($tic_grade)";
								}
								push @ytics, qq%'$tic_label' $i%;
								$prev_tic_grade = $tic_grade;
								
							}
							if (@ytics) {
								$set_y_tics = "set ytics (" . join(", ", @ytics) . ");\\";
							}
						}

						my $width = 350;
						if ($position_graph eq "matrix") {
							$width = 420;
						}

						my $plot_with = "linespoints linecolor rgb '#000000' linewidth 2";

						if ( $mean_graph_plot_with eq "boxes" ) {
							$plot_with = "boxes linecolor rgb '#000000' fill solid 1.0";
						}

						my $mean_gnuplot_code =
qq%set terminal png size $width,150;\\
set output '${doc_root}images/graphs/$stud_8-mean_small.png';\\
set datafile separator whitespace;\\
set xrange [0:$last_exam_index];\\
set yrange [$min_mean:$max_mean];\\
set grid ytics;\\
set grid xtics;\\
$set_x_tics
$set_y_tics
set tmargin 0.5;\\
set bmargin 1.2;\\
set boxwidth 0.8 relative;\\
plot '-' using 1:2 notitle with $plot_with;\\
%;

						my $incr_rank_plot = ($max_rank - $min_rank)/6;

						$incr_rank_plot = 1 if ($incr_rank_plot < 1);
						$incr_rank_plot = int($incr_rank_plot) + 1;
				
						my $position_gnuplot_code =
qq%set terminal png size 350,150;\\
set output '${doc_root}images/graphs/$stud_8-rank_small.png';\\
set xrange [0:$last_exam_index];\\
set yrange [$min_rank:$max_rank];\\
set grid ytics;\\
set grid xtics;\\
$set_x_tics
set ytics $min_rank,$incr_rank_plot,$max_rank;\\
set tmargin 0.5;\\
set bmargin 1.2;\\
plot '-' using 1:2 notitle with linespoints linecolor rgb '#000000' linewidth 2;\\
%;	

						my $data = "${mean_gnuplot_code};${position_gnuplot_code}";
						if ($position_graph eq "matrix") {
							$data = ${mean_gnuplot_code};
						}

						`echo '${mean_gnuplot_data}${position_overall_gnuplot_data}' | gnuplot -e "$data"`;

						
					}
					}

					#to ensure students whose marks_at_adm,avg are not
					#set don't interfere with the ranking, their marks_at_adm,avg
					#is set to -1
					#now set this value to N/A

					for my $stud_7 (keys %student_data) {
						if (${$student_data{$stud_7}}{"marks_at_adm"} == -1) {
							${$student_data{$stud_7}}{"marks_at_adm"} = "N/A";
						}
						foreach ($exam, keys %included_exams) {
							if (${$student_data{$stud_7}}{"mean_score_$_"} == -1) {
								${$student_data{$stud_7}}{"mean_score_$_"} = "N/A";
							}
							if (${$student_data{$stud_7}}{"mean_points_$_"} == -1) {
								${$student_data{$stud_7}}{"mean_points_$_"} = "N/A";
							}
							if (${$student_data{$stud_7}}{"total_marks_$_"} == -1) {
								${$student_data{$stud_7}}{"total_marks_$_"} = "N/A";
							}
							if (${$student_data{$stud_7}}{"total_points_$_"} == -1) {
								${$student_data{$stud_7}}{"total_points_$_"} = "N/A";
							}

							my @subjects = split/,/,${$student_data{$stud_7}}{"list_subjects"};
							for my $subj (@subjects) {
								if ( ${$student_data{$stud_7}}{"subject_${_}_${subj}"} == -1 ) {
									${$student_data{$stud_7}}{"subject_${_}_${subj}"} = "N/A";
								}
							}
						}
					}
					my %images = ();
					opendir (my $dirh, "${doc_root}images/mugshots/");
					if ($dirh) {	
						my @image_list = readdir($dirh);
						for my $image (@image_list) {
							if ($image =~ /^(\d+)\./) {
								my $adm = $1;
								$images{$adm} = "/images/mugshots/$image";
							}
						}
					}
					else {
						print STDERR "Could not open 'mugshots' directory: $!\n";	
					}

					my $res = "";

					for my $stud_6 (sort { ${$student_data{$a}}{"overall_rank_$exam"} <=> ${$student_data{$b}}{"overall_rank_$exam"} } keys %student_data) {
						
						next if (not exists $classes{lc(${$student_data{$stud_6}}{"class"})});
						#add new page to roll

							$res .=
qq!
<div style="width: 200mm; text-align: center; overflow: auto; border: 1px solid; padding: 0px; margin: 0px">
<img src="/images/letterhead2.png" alt="" href="/images/letterhead2.png" style="padding: 0px 0px 0px 0px; margin: 0px 0px 0px 0px">
<h3 style="padding: 0px 0px 0px 0px; margin: 0px 0px 0px 0px">$current_exam</h3>
</div>
!; 

						
						#left align the image,
						#show data on its left
						my $pic = 0; 
						if ($show_pictures) {
							$pic++;
							if (not exists $images{$stud_6} ) {
								$images{$stud_6} = "/images/mugshots/no_pic.png";
							}
						}
						if ($pic) {
							#organize with image

								my ($img_h,$img_w) = ("","");

								my $magick = Image::Magick->new;

								my ($width, $height, $size, $format) = $magick->Ping("${doc_root}$images{$stud_6}");	
								my $scale = 1;
								if ($width > 120 or $height > 150) {
									my $width_scale = 120/$width;
									my $height_scale = 150/$height;

									$scale = $width_scale < $height_scale ? $width_scale : $height_scale;
									$img_h = "height= '". $height * $scale . "px'";
									$img_w = "width= '" .  $width * $scale . "px'";
								}

								my $rowspan = 7;
								$rowspan += 2 if ($show_admission_data);
								$rowspan++ if ($show_dorm);

								$res .=
qq!
<div style="width: 50mm;color: white; background-color: black;border: solid 1px">STUDENT PROFILE</div>
<div style="border: 1px solid; width: 200mm; text-align: left">
<table cellspacing="0" cellpadding="0">
<tr><td rowspan="$rowspan"><img src="$images{$stud_6}" $img_h $img_w style="float: left; margin: 4px; border: solid 1px">
<tr><td style="font-weight: bold">Adm No.:<td>$stud_6
<tr><td style="font-weight: bold">Name:<td>${$student_data{$stud_6}}{"name"}
<tr><td style="font-weight: bold">Class:<td>${$student_data{$stud_6}}{"class"}
!;
								if ($show_admission_data) {
									$res .=	
qq!
<tr><td style="font-weight: bold">Marks at Admission:<td>${$student_data{$stud_6}}{"marks_at_adm"}
<tr><td style="font-weight: bold">Position at Admission:<td>${$student_data{$stud_6}}{"admission_rank"}
!;
								}
								my ($respons,$gayms,$klubs) = ("-","-","-");

								if (defined(${$student_data{$stud_6}}{"responsibilities"}) and ${$student_data{$stud_6}}{"responsibilities"} ne "") {
								$respons = ${$student_data{$stud_6}}{"responsibilities"};
								
								}

								if (defined(${$student_data{$stud_6}}{"sports_games"}) and ${$student_data{$stud_6}}{"sports_games"} ne "") {
									$gayms = ${$student_data{$stud_6}}{"sports_games"};
								}

								if (defined(${$student_data{$stud_6}}{"clubs_societies"}) and ${$student_data{$stud_6}}{"clubs_societies"} ne "") {
									$klubs = ${$student_data{$stud_6}}{"clubs_societies"};
								}

								$res .= 
qq!
<tr><td style="font-weight: bold">Responsibilities:<td>$respons
<tr><td style="font-weight: bold">Games/Sports:<td>$gayms
<tr><td style="font-weight: bold">Clubs/Societies:<td>$klubs
!;
								if ($show_dorm) {
									my $hse_dorm = ${$student_data{$stud_6}}{"house_dorm"};
									if (not defined $hse_dorm or $hse_dorm eq "") {
										$hse_dorm = "N/A";
									}
									$res .=
qq!
<tr><td style="font-weight: bold">$house_label:<td>$hse_dorm
!;								}
								$res .=
qq!
</table>
</div>
!;
							

						}
						else {
							#organize without image

								$res .=
qq!
<div style="width: 50mm;color: white; background-color: black;border: solid 1px">STUDENT PROFILE</div>
<div style="border: 1px solid; width: 200mm">
<table style="text-align: center; width: 200mm; word-wrap: normal" border="1">
<thead>
<th>Adm No.
<th>Name
<th>Class
!;
								if ($show_admission_data) {
									$res .=
qq!
<th>Marks at Admission
<th>Position at Admission
!;
								}
								
								$res .=
qq!
<th>Responsibilities
<th>Games/ Sports
<th>Clubs/ Societies
!;
								if ($show_dorm) {
									$res .=
qq!
<th>$house_label
!;								}
								$res .=
qq!
</thead>
<tbody>
<tr>
<td>$stud_6
<td>${$student_data{$stud_6}}{"name"}
<td>${$student_data{$stud_6}}{"class"}
!;
								if ($show_admission_data) {
									$res .=
qq!
<td>${$student_data{$stud_6}}{"marks_at_adm"}
<td>${$student_data{$stud_6}}{"admission_rank"}
!;
								}

								my ($respons,$gayms,$klubs) = ("-","-","-");

								if (defined(${$student_data{$stud_6}}{"responsibilities"}) and ${$student_data{$stud_6}}{"responsibilities"} ne "") {
								$respons = ${$student_data{$stud_6}}{"responsibilities"};
								
								}

								if (defined(${$student_data{$stud_6}}{"sports_games"}) and ${$student_data{$stud_6}}{"sports_games"} ne "") {
									$gayms = ${$student_data{$stud_6}}{"sports_games"};
								}

								if (defined(${$student_data{$stud_6}}{"clubs_societies"}) and ${$student_data{$stud_6}}{"clubs_societies"} ne "") {
									$klubs = ${$student_data{$stud_6}}{"clubs_societies"};
								}

								$res .= 
qq!
<td>$respons
<td>$gayms
<td>$klubs
!;
								if ($show_dorm) {
									my $hse_dorm = ${$student_data{$stud_6}}{"house_dorm"};
									if (not defined $hse_dorm or $hse_dorm eq "") {
										$hse_dorm = "N/A";
									}
									$res .=
qq!
<td>$hse_dorm
!;
								}
								$res .=
qq!
</tbody>
</table>
</div>
!;
							
						}
						#results proper
						#----------
						#|	  |
						#|******* |
						#|******* |
						#|	  |
						#|_ _ _ _ |
						#
						#** - Results proper
						my $row = 1;
						%data = ();

							$res .= 
qq!
<div style="width: 50mm;color: white; background-color: black;border: solid 1px">RESULTS</div>
<table border="1" style="text-align: left; width: 200mm" cellspacing="0" cellpading="0">
<thead>
<th>Subject
!;
							if ( keys %included_exams ) {
								foreach ( sort { $included_exams_age{$a} <=>  $included_exams_age{$b} } keys %included_exams) {
									$res .= "<th>$_";
								}
								$res .= "<th>$exam";
							}
							else {
								$res .= "<th>Marks";
							}

							if ($show_grade) {
								$res .= "<th>Grade";
							}

							if ($show_points) {
								$res .= "<th>Points"
							}

							if ($show_subject_position) {
								$res .= "<th>Subject Position";
							}
							if ($show_remarks) {
								$res .= "<th>Remarks";
							}
							if ($show_input_by) {
								$res .= "<th>Teacher";
							}
							$res .=
qq!
</thead>
<tbody>
!;
						
					
						for (my $j = 0; $j < @valid_subjects; $j++) {
							if (exists ${$student_data{$stud_6}}{"subject_${exam}_$valid_subjects[$j]"}) {
								$row++;
								my $score = ${$student_data{$stud_6}}{"subject_${exam}_$valid_subjects[$j]"};
								my $grade = get_grade($score);
								my $remark = undef;

									$res .= 
qq!
<tr>
<td style="font-weight: bold">$valid_subjects[$j]
!;
		
									#displaying more than 1 exam
									if (keys %included_exams) {			
										foreach (sort { $included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams) {
											my $score = ${$student_data{$stud_6}}{"subject_${_}_$valid_subjects[$j]"};
											$res .= qq!<td>$score!;
										}
									}

											
									$res .= qq!<td style="font-weight: bold">$score!;	
								
								
									if ($show_grade) {
										$res .= "<td>$grade";
									}

									if ($show_points) {
										$res .= "<td>" . $points{$grade};
									}

									if ($show_subject_position) {
										$res .= "<td>" . ${$student_data{$stud_6}}{"position_subject_${exam}_$valid_subjects[$j]"} . " of " . $subject_class_sizes{$valid_subjects[$j]};  
									}
									if ($show_remarks) {
										$remark = $remarks{$grade};
										$res .= "<td>$remark";
									}
									if ($show_input_by) {
										my $ta = "-";
										if (exists $teachers{lc($valid_subjects[$j] . "_" . ${$student_data{$stud_6}}{"class"})}) {
											$ta = $teachers{lc($valid_subjects[$j] . "_" . ${$student_data{$stud_6}}{"class"})}; 
											#$ta = $teachers{"${exam}_$valid_subjects[$j]"};
										}
										$res .= "<td>$ta";
									}
								
							}
						}	
	
						#results summary
						my $class_size = ${$stud_rolls{${$student_data{$stud_6}}{"roll"}}}{"size"};
						my $class_grad_year = ${$stud_rolls{${$student_data{$stud_6}}{"roll"}}}{"grad_year"};
						my $yr_size = 0;
					
						for my $roll (keys %stud_rolls) {
							next unless (${$stud_rolls{${$student_data{$stud_6}}{"roll"}}}{"grad_year"} eq $class_grad_year);
							$yr_size += ${$stud_rolls{$roll}}{"size"};
						}

							$res .= 
qq!
<tr>
<td style="font-weight: bold;color: white; background-color: black">Mean Score
!;			
							if (keys %included_exams) {	
								foreach (sort {$included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams) {
									my $mean_score = ${$all_exams_mean_scores{$stud_6}}{"mean_score_$_"}; #${$student_data{$stud_6}}{"mean_score_$_"};
									if ($mean_score =~ /^\d+(\.\d+)?$/) {
										$mean_score = sprintf "%.${dp}f", $mean_score;
									}
									$res .= qq!<td style="color: white; background-color: black">$mean_score!;
								}
							}

							my $mean_score = ${$student_data{$stud_6}}{"mean_score_$exam"};
							if ($mean_score =~ /^\d+(\.\d+)?$/) {
								$mean_score = sprintf "%.${dp}f", $mean_score;
							}
								
							my $exam_yr = $current_year;

							if ( exists $included_exams_age{$exam} ) {
								$exam_yr = (localtime $included_exams_age{$exam} )[5] + 1900;
							}

							my $yr_study = ( $exam_yr - $start_yr ) + 1;

							my $mean_grade = get_grade(${$student_data{$stud_6}}{"mean_score_$exam"});

							if ( exists $rank_by_points{$yr_study} ) {
								$mean_grade = $points_to_grade{round(${$student_data{$stud_6}}{"mean_points_$exam"})};
							}

							my $mean_remark = undef;

							$res .= qq!<td style="font-weight: bold; color: white; background-color: black">$mean_score!;

							my $extra_cols = scalar(keys %included_exams);

							my $colspan = 1 + $extra_cols;

							if ($show_grade) {
								$res .= qq!<td style="font-weight: bold">$mean_grade!;
								$colspan++;
							}

							if ($show_points) {

								my $mean_points = $points{$mean_grade};

								if ( exists $rank_by_points{$yr_study} ) {
									$mean_points = round(${$student_data{$stud_6}}{"mean_points_$exam"});
								}
								$res .= qq!<td style="font-weight: bold">$mean_points!;

								$colspan++;
							}

							if ($show_subject_position) {
								$res .= qq!<td>&nbsp;!;
								$colspan++;
							}
							if ($show_remarks) {
								$mean_remark = $remarks{$mean_grade};
								$res .= qq!<td style="font-weight: bold">$mean_remark!;
								$colspan++;
							}

							if ($show_input_by) {
								$res .= "<td>&nbsp;";
								$colspan++;
							}

							my $surplus_cols = $colspan - (scalar(keys %included_exams) + 1);

							#total marks
							$res .= qq!<tr style="font-weight: bold"><td>Total Marks!;
							foreach ( (sort {$included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams), $exam) {
								$res .= qq!<td>${$student_data{$stud_6}}{"total_marks_$_"}!;	
							}

							$res .= qq!<td style="border: hidden;vertical-align: top; font-weight: normal" rowspan="4" colspan="$surplus_cols"><span style="text-decoration: underline; font-weight: bold">Grading System</span><br>!;
						
							my @grading_str_bts = split/,/,$grading_str;
							my $reformd_grading_str = "";

							for my $grading_str_bt (@grading_str_bts) {
								my $len = length($grading_str_bt);
								if ($grading_str_bt =~ /^([^:]+)\:(.*)$/) {
									my $range = $1;
									my $grade = $2;

									#produce fixed column width (9) str	
									my $spaces = "&nbsp;" x (12 - $len);
									$reformd_grading_str .= qq!$range:&nbsp;<span style="font-weight: bold">$grade</span>$spaces !;
								}	
							}

							$res .= $reformd_grading_str;

							#total points
							$res .= qq!<tr style="font-weight: bold"><td>Total Points!;
							foreach ( (sort {$included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams), $exam) {
								$res .= qq!<td>${$student_data{$stud_6}}{"total_points_$_"}!;	
							}

							#$res .= qq!<td style="border: hidden" colspan="$surplus_cols">!;

							#Class position
							$res .= qq!<tr style="font-weight: bold"><td>Class Position!;

							foreach ( (sort {$included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams), $exam) {

								my $class_rank = "";
								
								if ($_ eq $exam) {
									$class_rank = qq!${$student_data{$stud_6}}{"class_rank_$_"} of $class_size!;
								}

								$res .= qq!<td>$class_rank!;
							}

							#$res .= qq!<td style="border: hidden" colspan="$surplus_cols">!;

							$res .= qq!<tr style="font-weight: bold"><td style="color: white; background-color: black">Overall Position!;

							#Overall position
							foreach ( (sort {$included_exams_age{$a} <=> $included_exams_age{$b} } keys %included_exams), $exam) {	

								#$res .= qq!<td style="color: white; background-color: black">${$student_data{$stud_6}}{"overall_rank_$_"}&nbsp;of&nbsp;$yr_size!;
								$res .= qq!<td style="color: white; background-color: black">${$all_exams_ranks{$stud_6}}{$_}&nbsp;of&nbsp;$yr_size!;							
							}
							#$res .= qq!<td style="border: hidden" colspan="$surplus_cols">!;
			
							$res .= 
qq!
</tbody>
</table>

<hr style="height: 2px">
!;
						#}
						#extra-curriculae
						#----------
						#|	  |
						#|	  |
						#|.-.-.-.-|
						#|	  |
						#|_ _ _ _ |
						#
						#** - Results proper
						#extra-curriculars
						my ($respons,$gayms,$klubs) = ("-","-","-");

							my $rank_graph = "/images/no_graph.png";
							my $mean_graph = "/images/no_graph.png";

							if ( -e "${doc_root}/images/graphs/$stud_6-rank_small.png" ) {
								$rank_graph = "/images/graphs/$stud_6-rank_small.png";
							}
							if ( -e "${doc_root}/images/graphs/$stud_6-mean_small.png") {
								$mean_graph = "/images/graphs/$stud_6-mean_small.png";
							}
	
							if ( $position_graph eq "matrix" ) {

								
								my %progress_graph = ();

								for ( my $i = $start_yr; $i <= $grad_yr; $i++ ) {
									$progress_graph{$i} = "";
								}

								my $cell_data = "";
								my $exams_seen = 0;
						
								for my $exam_n_5 (sort { $all_exams{$a} <=> $all_exams{$b} } keys %all_exams) {

									my @exam_time_bts = localtime($all_exams{$exam_n_5});
									my $exam_yr = $exam_time_bts[5] + 1900;

									#this was added to tackle repeaters
									next unless (exists $progress_graph{$exam_yr});

									my $rank = "&nbsp;-&nbsp;";

									if (exists ${$all_exams_mean_scores{$stud_6}}{"mean_score_$exam_n_5"}) {	
										$rank = sprintf("%3d", ${$all_exams_ranks{$stud_6}}{$exam_n_5});
										$rank =~ s/ /&nbsp;/g;
									}
									#bold current exam
									if ( $exam_n_5 eq $exam ) {
										#found a ridiculous situation where the position in
										#<all_exams_ranks> is different from the one in
										#<student_data>.
										#conceal this.
										#<YES, I'M ASHAMED>
										my $th_rank = sprintf("%3d", ${$student_data{$stud_6}}{"overall_rank_${exam_n_5}"});
										$th_rank =~ s/ /&nbsp;/g;

										$progress_graph{$exam_yr} .= qq!<span style="font-weight: bold">$th_rank</span>&nbsp;!;
									}
									else {	
										$progress_graph{$exam_yr} .= "$rank&nbsp; ";
									}	

								}

								my $stud_yrs_study = ($grad_yr - $start_yr) + 1;
								my $mid_yr = ceil($stud_yrs_study / 2);
	
								my $padding = "";
								#add blank cell incase the 2nd row is not 
								unless ( ($stud_yrs_study % 2) == 0) {
									$padding = "<TD>&nbsp;";
								}

								my $progress_matrix = ""; 
								my $yrs_seen = 0;

								#write either a new cell or
								#a new row
								for my $exam_yr_0 (sort { $a <=> $b } keys %progress_graph) {

									if ( $yrs_seen++ == $mid_yr ) {
										$progress_matrix .= "<TR>";
									}

									#don't write <td> if 1st cell
									my $td = qq!<TD style="font-weight: 0.6em; vertical-align: top">!;
									if ($yrs_seen == 1) {
										$td = "";
									}
									#write year header
									$progress_matrix .= qq!$td<SPAN style="text-align: left; color: white;background-color: black">$exam_yr_0</SPAN><BR>$progress_graph{$exam_yr_0}</TD>!;

								}

								$progress_matrix .= $padding;
								

								$res .=
qq!
<table border="1" style="width: 200mm; table-layout: fixed" cellspacing="0" cellpadding="0">
<tr>
<td style="color: white; background-color: black; width: 60%">Student's Progress(Mean score)
<td style="color: white; background-color: black; width: 40%" colspan="$mid_yr">Student's Progress(Position)
<tr>
<td style='width: 60%; text-align: center' rowspan="2"><img src="$mean_graph" alt="Student's Progress(Mean score)" href="$mean_graph">
<td style='width: 40%; font-weight: 0.6em; vertical-align: top'>${progress_matrix}
</table>
!;	
							}
							else {

								$res .=
qq!
<table border="1" style="width: 200mm; table-layout: fixed" cellspacing="0" cellpadding="0">
<tr>
<td style="color: white; background-color: black">Student's Progress(Position)
<td style="color: white; background-color: black">Student's Progress(Mean score)
<tr>
<td><img src="$rank_graph" alt="Student's Progress(Position)" href="$rank_graph">
<td><img src="$mean_graph" alt="Student's Progress(Mean score)" href="$mean_graph">
</table>
!;	
							}
							
							#fee balances
							if ( $show_fees ) {

								my $arrears = $student_data{$stud_6}->{"arrears"};
								my $arrears_prepayment = "Arrears";

								
								my $f_arrears = "N/A";
								my $f_next_term_fees = "N/A";

								my $next_term_fees =$student_data{$stud_6}->{"next_term_fees"};
								my $total = 0;

								if ( $arrears =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {
									if ($arrears < 0) {
										$arrears_prepayment = "Prepayment";
									}

									$total += $arrears;
									$f_arrears = $currency . " " . format_currency(abs($arrears));
								}

								if ($next_term_fees =~ /^\d{1,10}(\.\d{1,2})?$/) {
									$total += $next_term_fees;
									$f_next_term_fees = $currency . " " . format_currency($next_term_fees);
								}

								my $f_total = $currency . " " . format_currency($total);
								
								$res .=
qq!
<div style="width: 50mm;color: white; background-color: black;border: solid 1px">FEES</div>
<table  style="width: 200mm; table-layout: fixed" cellspacing="0" cellpadding="0">
<TR style="font-size: 0.8em"><TD><span style="font-weight: bold; width: 30%">$arrears_prepayment:</span>&nbsp;$f_arrears<TD><span style="font-weight: bold; width: 50%">Next Term's Fees:</span>&nbsp;$f_next_term_fees<TD><span style="font-weight: bold; width: 30%">Total:</span>&nbsp;$f_total
</table>
<hr style="height: 2px">
!;

							}	
							#comments

							my ($principal_formatted, $class_ta_formatted) = ("", "");

							if ($principal ne "") {
								$principal_formatted = "($principal)";
							}
							
							if (exists $class_teachers{lc(${$student_data{$stud_6}}{"class"})}) {
								$class_ta_formatted = "(" . $class_teachers{lc(${$student_data{$stud_6}}{"class"})} . ")";
							}

							my $dots = "." x 200;
							my $principals_dots = $dots;

							if ($auto_principals_remarks) {
							
								my $mean_score = ${$student_data{$stud_6}}{"mean_score_$exam"};
								if ($mean_score =~ /^\d+(\.\d+)?$/) {
									$mean_score = sprintf "%.${dp}f", $mean_score;
								}
							
								my $mean_grade = get_grade(${$student_data{$stud_6}}{"mean_score_$exam"});

								if ( exists $principals_remarks{$mean_grade} ) {
									
									$principals_dots = $principals_remarks{$mean_grade} . " ";
									
									my $rem = "&nbsp;" x int (0.5 * (200 - length($principals_dots)));
									$principals_dots .= $rem;	
								}

							}

							$res .=
qq!
<table border="1" style="width: 200mm; table-layout: fixed; word-wrap: break-word; text-align: left">
<tr>
<td>
<span style="font-weight: bold; text-decoration: underline">Class Teacher$class_ta_formatted</span><br>
<span style="line-height: 200%">$dots</span>

<td>
<span style="font-weight: bold; text-decoration: underline">Principal$principal_formatted</span><br>
<span style="line-height: 200%">$principals_dots</span>

<tr>
<td colspan="2">
<br><span style="font-weight: bold; text-decoration: underline">Parent/Guardian's Signature</span>.................................<span style="font-weight: bold; text-decoration: underline">Date</span>..................................
</table>
<div style="align: left; text-align: center; width: 200mm"><h3>$report_card_footer</h3></div>
<br class="new_page">
!;
						#}
					}

					#save pdf

						$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
<STYLE type="text/css">

\@media print {
	body {
		margin-top: 0px;
		margin-bottom: 0px;
		padding: 0px;
		font-size: 10pt;
		font-family: "Times New Roman", serif;	
	}

	div.no_header {
		display: none;
	}

	br.new_page {
		page-break-after: always;
	}

	.small_font {
		font-size: 8pt;
	}
}

\@media screen {
	div.noheader {}
	.small_font {
		font-size: 0.8em;
	}
}

br.short_break {
	line-height: 0;
	padding: 0;
	margin: 0;	
}

</STYLE>
</head>
<body>
<div class="no_header">
$header
</div>
$res
<body>
</html>
*;
						#log report card gen	
						my @today = localtime;
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

						open (my $log_f, ">>${log_d}user_actions-$day_month_yr.log");
       						if ($log_f) {
               						@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log view report cards for $id due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
							my $viewed_classes = join (',', keys %classes);
 
	 						print $log_f "$id VIEW REPORT CARDS ($viewed_classes) $time\n";
							flock ($log_f, LOCK_UN);
               						close $log_f;
       						}
						else {
							print STDERR "Could not log view report cards for $id: $!\n";
						}
					#}
				}

				else {
					$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<em>None of the student rolls in the system match your selection.</em> Perhaps these rolls have not been created yet?
</body>
</html>
};

				}
			}
		}

		#confirm tokens issue
		else {
			$content =		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<em>Invalid authorization tokens sent. Reload this page to continue.</em>
</body>
</html>
};
		}
	}

	else {
		if (@authd_classes) {
			my %grouped_classes = ();
			my %exams = ();
	
			#Group the classes by year
			for my $class (@authd_classes) {
				if ($class =~ /(\d+)/) {
					my $yr = $1;
					
					$grouped_classes{$yr} = [] unless (exists $grouped_classes{$yr});
					push @{$grouped_classes{$yr}}, $class;
				}
			}	
	 
			my $prep_stmt2 = $con->prepare("SELECT exam_name,max(time) FROM marksheets GROUP BY exam_name");
			if ($prep_stmt2) {
				my $rc = $prep_stmt2->execute();
				if ($rc) {
					while (my @rslts = $prep_stmt2->fetchrow_array()) {
						$exams{$rslts[0]} = $rslts[1];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt2->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt2->errstr, $/;
			}
	
			my $classes_select = '';
			my $exam_select = '';
	
			if (scalar(@authd_classes) > 1) {
				$classes_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL style="font-weight: bold">Class</LABEL>};

				foreach (sort keys %grouped_classes) {
					my @yr_classes = @{$grouped_classes{$_}};

					$classes_select .= "<TD>";
					for (my $i = 0; $i < scalar(@yr_classes); $i++) {
						$classes_select .= qq{<INPUT type="checkbox" name="class_$yr_classes[$i]" id="$yr_classes[$i]" value="$yr_classes[$i]"><LABEL for="class_$yr_classes[$i]" id="$yr_classes[$i]_label">$yr_classes[$i]</LABEL>};
						#do not append <BR> to the last class
						if ($i < $#yr_classes) {
							$classes_select .= "<BR>";
						}
					}
				}
				$classes_select .= "</table>"; 
			}
			else {
				my $class = $authd_classes[0];
				$classes_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL for="class_$class" style="font-weight: bold">Class</LABEL><TD><INPUT readonly type="text" name="class_$class" value="$class"></TABLE>};
			}
			$exam_select .= qq{<TABLE cellspacing="5%"><TR><TD><LABEL style="font-weight: bold" for="exam">Exam</LABEL><TD><SELECT name="exam">};
			
			foreach ( sort { $exams{$a} <=> $exams{$b} } keys %exams) {	
				if ($_ eq $current_exam) {
					$exam_select .= qq{<OPTION selected value="$_">$_</OPTION>}; 
				}
				else {
					$exam_select .= qq{<OPTION value="$_">$_</OPTION>}; 
				}
			}
			$exam_select .= "</SELECT></TABLE>";
	
			my $included_exams = "";

			if (keys %exams > 1) {
				$included_exams .= qq{Also include the following exams in the report card:<BR><TABLE cellspacing="5%">};
				my $include_cntr = 0;

				foreach (sort { $exams{$a} <=> $exams{$b} } keys %exams) {
					$included_exams .= qq{<TR><TD><INPUT type="checkbox" name="include_$include_cntr" value="$_"><LABEL for="include_$include_cntr">$_</LABEL>};
					$include_cntr++;
				}
				$included_exams .= "</TABLE>";
			}

			my $conf_code = gen_token();
			$session{"confirm_code"} = $conf_code;
			$update_session++;	
			$content =
		
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<FORM action="/cgi-bin/genreportcards.cgi" method="POST">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<p>$classes_select
<p>$exam_select
<p>$included_exams

<table>
<tr>
<td><INPUT type="submit" name="view" value="View Report Cards">
<!--<td><INPUT type="submit" name="download" value="Download Report Cards">-->
</table>

</FORM>
</body>
</html>
};

		}
		else {

			my $err = "<em>Sorry you are not authorized to generate any report cards.</em> To continue, obtain an up to date token with the appropriate privileges from the administrator.";
			if ($full_user) {
				$err = "<em>The 'classes' system variable has not been properly configured.</em> To continue, change this system variable through the administrator panel.";
			}

			$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title> Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$err
</body>
</html>
};	
	
		}
	}
}

else { 
	$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title> Spanj :: Exam Management Information System :: Generate Report Cards</title>
</head>
<body>
$header
<em>Sorry you are not authorized to generate any report cards.</em> To continue, obtain an up to date token with the appropriate privileges from the administrator.
</body>
</html>
};
}

	print "Status: 200 OK\r\n";
	print "Content-Type: text/html; charset=UTF-8\r\n";
#}

my $len = length($content);
print "Content-Length: $len\r\n";

if ($update_session) { 
	my @new_sess_array = ();
	for my $sess_key (keys %session) {	
		push @new_sess_array, $sess_key."=".$session{$sess_key};        
	}
	my $new_sess = join ('&',@new_sess_array);
	print "X-Update-Session: $new_sess\r\n";
}

print "\r\n";
print $content;
$con->disconnect();

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub grade_sort {
	#idea is to try & give the student
	#the best grade their marks can
	#earn. Presumably, higher marks == better grade

		
	#both have a minimum
	#use the higher of the 2
	if (exists ${$grading{$a}}{"min"} and exists ${$grading{$b}}{"min"}) {
		return ${$grading{$b}}{"min"} <=> ${$grading{$a}}{"min"};
	}
	#both have a maximum
	#use the higher of the 2
	elsif (exists ${$grading{$a}}{"max"} and exists ${$grading{$b}}{"max"}) {
		return ${$grading{$b}}{"max"} <=> ${$grading{$a}}{"max"};
	}
	elsif (exists ${$grading{$a}}{"eq"} and exists ${$grading{$b}}{"eq"}) {
		return ${$grading{$b}}{"eq"} <=> ${$grading{$a}}{"eq"};
	}
	#$a has eq, $b doesn't 
	if (exists ${$grading{$a}}{"eq"}) {
		return 1;
	}
	#$b has eq, $a doesn't
	else {
		return -1;
	}  

	#$a has a min set, $b doesn't 
	if (exists ${$grading{$a}}{"min"}) {
		return 1;
	}
	#$b has a min set, $a doesn't
	else {
		return -1;
	}
}

sub get_grade {
	my $grade = "N/A";
	return "N/A" unless (@_);
	my $score = $_[0];

	return "N/A" unless ($score =~ /^\d+(\.\d+)?$/);

	GRADE: for my $tst_grade (sort grade_sort keys %grading) {
		my %tst_conds = %{$grading{$tst_grade}};
		#check equality
		if (exists $tst_conds{"eq"}) {
			if ($score == $tst_conds{"eq"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
		elsif (exists $tst_conds{"min"}) {
			if ($score > $tst_conds{"min"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
		elsif (exists $tst_conds{"max"}) {
			if ($score < $tst_conds{"max"}) {
				$grade = $tst_grade;
				last GRADE;		
			}
		}
	}
	return $grade;
}

#width,height,data
sub draw_table {
	return unless (scalar(@_) > 1);	
	my $width = shift;
	my $height = shift;	
	
	my ($display_width, $display_height) =  ($urx - $llx, $lly - $ury);
	
	my $x_offset = $llx + int ( ($display_width - $width ) / 2 );

	my $y_offset =  $lly - int ( ($display_height - $height ) / 2 );	

	my ($no_cols,$no_rows) = (0,0);	

	my %widths  = ();
	my %heights = ();
	my ($widths_total,$heights_total) = (0,0);
	my $overflows = 0;

	WRAP:
	{
		%widths  = ();
		%heights = ();
		($widths_total,$heights_total) = (0,0);	

		for my $cell (keys %data) {
			my $cell_dta = "undef";
			if (exists ${$data{$cell}}{"data"} and defined  ${$data{$cell}}{"data"}) {
				$cell_dta = ${$data{$cell}}{"data"};
			}	

			my $font_size = 12;	
			if ($cell =~ /^(\d+),(\d+)$/) {	
				my ($row,$col) = ($1,$2);
				my $cell_data = "";
				if (exists ${$data{$cell}}{"data"} and defined ${$data{$cell}}{"data"}) {
					$cell_data = ${$data{$cell}}{"data"};
				}

				my $cell_data_width = 0;	

				if ( exists ${$data{$cell}}{"font-size"} ) {
					my $possib_font_size = ${$data{$cell}}{"font-size"};
					if ($possib_font_size =~ /^\d+$/) {
						$font_size = $possib_font_size;
					}
				}
				if ( exists ${$data{$cell}}{"font-type"} ) {
					my $possib_font_name = ${$data{$cell}}{"font-type"};
					if ( exists $core_fonts{$possib_font_name} ) {
						my $font_name = $possib_font_name;
						if ($font_name =~ /Bold/) {	
							$font_size *= 1.2;
						}
					}
				}
			
				if ($auto_resize) {
					if ($cell_data =~ /\n/m) {	
						my @lines = split/\n/m,$cell_data;
						for my $line (@lines) {	
							my $width = guess_width($line, $font_size) + $font_size;
							if ($width > $cell_data_width) {	
								$cell_data_width = $width;
							}
						}
					}
					else {
						$cell_data_width = guess_width($cell_data, $font_size) + $font_size;
					}
 
					if (not exists $widths{$col}) {
						$widths{$col} = $cell_data_width;
						$widths_total += $cell_data_width;
					}
					else {
						if ($cell_data_width > $widths{$col}) {
							#replace existing widest both in %widths
							#and in widths_total 
							$widths_total -= $widths{$col};
							$widths{$col} = $cell_data_width;
							$widths_total += $cell_data_width;
						}
					}
				
					my $cell_data_height = $font_size * 2;
					if ($cell_data =~ /\n/m) {
						my @content_lines = split /\n/m, $cell_data;
						$cell_data_height = scalar(@content_lines) * $font_size;
						my $inter_line_spc = int ((scalar(@content_lines) - 1) * $font_size * 0.5);
						#my $inter_line_spc = (scalar(@content_lines) - 1) * $font_size * 0.5;
						$cell_data_height += $inter_line_spc + $font_size;
					}

					if (not exists $heights{$row}) {
						$heights{$row} = $cell_data_height;
						$heights_total += $cell_data_height;
					}
					else {
						if ($cell_data_height > $heights{$row}) {
							$heights_total -= $heights{$row};
							$heights{$row} = $cell_data_height;
							$heights_total += $cell_data_height;
						}
					}
				}
				if ($row > $no_rows) {
					$no_rows = $row;
				}
				if ($col > $no_cols) {
					$no_cols = $col;
				}
			}
		}	
	
		#try wrapping lines around spaces
		if ( $widths_total  > $width or $heights_total > $height ) {
			$overflows = 1;
	
			my $found_space = 0;
			J: for my $cell3 (sort { length( ${$data{$b}}{"data"} ) <=> length( ${$data{$a}}{"data"} ) }  keys %data) {
				
				my $cell3_data = ${$data{$cell3}}{"data"};	

				if ($cell3_data =~ /(\h+)/m) {
					$found_space++;
	
					my $new_line = "\n";
					$cell3_data =~ s/\h+/$new_line/m;

					#check possible exceed of table height
					#every split will add 1.5 font size to heights_total

					my $font_size = 12;
					
					if ( exists ${$data{$cell3}}{"font-size"} ) {
						my $possib_font_size = ${$data{$cell3}}{"font-size"};
						if ($possib_font_size =~ /^\d+$/) {
							$font_size = $possib_font_size;
						}
					}
					if ( exists ${$data{$cell3}}{"font-type"} ) {
						my $possib_font_name = ${$data{$cell3}}{"font-type"};
						if ( exists $core_fonts{$possib_font_name} ) {
							my $font_name = $possib_font_name;
							if ($font_name =~ /Bold/) {	
								$font_size *= 1.2;
							}
						}
					}

					#exceeded. break out in a sweat
					if ($heights_total + ($font_size * 1.5) > $height) {	
						$found_space = 0;
						last J; 
					}
					${$data{$cell3}}{"data"} = $cell3_data;
					last J;
				}
			}
	
			if ($found_space) {
				redo WRAP;
			}
			else {
				#reduce font sizes
				#up to 0pts---yeah, that's daft...
				my $new_font = 11;
				for my $cell4 (keys %data) {
					if (exists ${$data{$cell4}}{"font-size"} and ${$data{$cell4}}{"font-size"} =~ /^\d+$/) {
						$new_font = ${$data{$cell4}}{"font-size"} - 1;
					}
					if ($new_font < 0) {	
						last WRAP;
					}
					else {	
						${$data{$cell4}}{"font-size"} = $new_font;
					}
				}
				redo WRAP; 
			}
		}
		else {
			$overflows = 0;
			last WRAP;
		}
	}

	if ($auto_resize) {
		#resize each column
		#in ratio of their widest cells	

		foreach (keys %widths) {	
			$widths{$_} = int( ($widths{$_} / $widths_total) * $width);	
#			$widths{$_} = ($widths{$_} / $widths_total) * $width;
		}

		foreach (keys %heights) {	
			$heights{$_} = int( ($heights{$_} / $heights_total) * $height);	
#			$heights{$_} = ($heights{$_} / $heights_total) * $height;
		}
	}

	#default row,col sizes
	#assume uniform col,row spacing
	my ($row_height,$col_width) = (int($height / $no_rows), int($width / $no_cols));
#	my ($row_height,$col_width) = ($height / $no_rows, $width / $no_cols);
	my $text = $page->text(); 
	my $graph = $page->gfx();
	
	#draw enclosing box...
		
	$graph->move($x_offset, $y_offset);
	$graph->line($x_offset, $y_offset - ($row_height * $no_rows));
	#$graph->move($x_offset, $y_offset - $height);
	
	#$graph->line($x_offset + $width, $y_offset - $height);
	$graph->move($x_offset + $width, $y_offset - $height);

	#$graph->line($x_offset + $width, $y_offset);
	$graph->move($x_offset + sprintf("%.0f", $no_cols * $col_width), $y_offset);
	
	$graph->line($x_offset, $y_offset);
	$graph->stroke();

	#draw individual cells
#	$y_offset = $display_height - int ( ($display_height - $height ) / 2 );	
#	$y_offset = $display_height - ($display_height - $height ) / 2;
	
	my ($cell_x, $cell_y) = ($x_offset, $y_offset);	
	my ($row,$col) = (1,1);
			
	for my $cell2 (sort cell_ref_sort keys %data) {	
		if ($cell2 =~ /^(\d+),(\d+)$/) {
			($row,$col) = ($1,$2);
		}
		#set row,col sizes as appropriate
		#if auto_resize is on
		if ($auto_resize) {
			$row_height = $heights{$row};
			$col_width  = $widths{$col};	
		}
		
		#don't draw the line @ bottom
		#it has been sketched for thee
		#has double role- avoids the issue
		#created by the int() rounding of
		#row_height 
		#if ($row < $no_rows) {
			my $correction = 0;
			unless ( $width  / $no_cols % 10 == 0 ) {
				if ($col == $no_cols) {	
					#$correction = 1;
				}
			}
			#no bottom border
			#kludge for implementing rowspan
			unless (exists ${$data{$cell2}}{"border-bottom"} and ${$data{$cell2}}{"border-bottom"} eq "0") {
				$graph->move($cell_x, $cell_y - $row_height);	
				$graph->line($cell_x + $col_width + $correction, ($cell_y - $row_height));	
			}
		#}
		#do not draw the last line on right
		#if ($col < $no_cols) {
			my ($l_correction, $u_correction) = (0,0);
			#unless ($height / $no_rows) % 10 == 0) {
				if ( $row == $no_rows ) {
					unless ( $height / $no_rows  % 10 == 0 ) {
						#$l_correction = 3;
					}
				}
				if ($row == 1) {
					unless ( $height / $no_rows % 10 == 0 ) {
						#$u_correction = 3;
					}
				}
			#}
			unless (exists ${$data{$cell2}}{"border-right"} and ${$data{$cell2}}{"border-right"} eq "0") {
				$graph->move($cell_x + $col_width, $cell_y - $u_correction);
				$graph->line($cell_x + $col_width, ($cell_y - $row_height) - $l_correction);	
			}
		#}

		my $cell_content = ${$data{$cell2}}{"data"};	
	
		my $font_size = 12;
		my $font_name = "Times-Roman";
		my $bold = 0;
		my $font_size_scale = 1;

		if (exists ${$data{$cell2}}{"font-size"}) {
			my $possib_font_size = ${$data{$cell2}}{"font-size"};
			if ($possib_font_size =~ /^\d+$/) {		
				$font_size = $possib_font_size;
			}
		}

		if (exists ${$data{$cell2}}{"font-type"}) {
			my $possib_font_name = ${$data{$cell2}}{"font-type"};
			if (exists $core_fonts{$possib_font_name}) {
				$font_name = $possib_font_name;
				if ($font_name =~ /Bold/) {
					$bold = 1;
					$font_size_scale = 1.2;
				}
			}
		}
		my $font = $pdf->corefont($font_name);
		my $v_align = "middle";
		my $h_align = "left";
		
		if ($cell_content =~ /^\d+(\.\d+)?$/) {
			$h_align = "right";	
		}

		#valid v-aligns: top, bottom, middle
		if (exists ${$data{$cell2}}{"v-align"}) {
			my $possib_v_align = ${$data{$cell2}}{"v-align"};
			if ($possib_v_align =~ /^(?:top)|(?:bottom)|(?:middle)$/i) {
				$v_align = lc($possib_v_align);
			}
		}

		#valid h-align: left, right, center, justify
		if (exists ${$data{$cell2}}{"h-align"}) {
			my $possib_h_align = ${$data{$cell2}}{"h-align"};
			if ($possib_h_align =~ /^(?:left)|(?:right)|(?:center)|(?:justify)$/i) {
				$h_align = lc($possib_h_align);
			}
		}

		
	
		my ($content_width, $content_height) = (guess_width($cell_content, $font_size * $font_size_scale), $font_size * $font_size_scale);	
	
		#detect & fix overflows (by wrapping/reducing font size/resizing rows,cols);
	
		my $multi_line = 0;
		my @lines = ();
		if ($cell_content =~ /\n/m) {
			$multi_line++;
			@lines = split/\n/m,$cell_content;
			my ($width, $height) = (-1,-1);	
			foreach (@lines) {
				my $possib_width = guess_width($_,$font_size * $font_size_scale);
				if ($possib_width > $width) {
					$width = $possib_width;
				}
			}
			$content_width = $width;
			$content_height = scalar(@lines) * $font_size * $font_size_scale;
		}
	
		my ($content_offset_x, $content_offset_y) = (-1, -1);

		my (%center_x_offsets, %right_x_offsets);

		my $half_em = int($font_size * $font_size_scale * 0.5);
#		my $half_em = $font_size * $font_size_scale * 0.5;

		#allow half an em above
		if ($v_align eq "top") {
			$content_offset_y = $cell_y - ($half_em + ($font_size * $font_size_scale));
		}

		#allow half an em below
		elsif ($v_align eq "bottom") {
			if ($multi_line) {
				my $inter_line_spc = (scalar(@lines) - 1) * $font_size * $font_size_scale * 0.5;
				my $content_below_line = (scalar(@lines) - 1) * $font_size * $font_size_scale;
				$content_offset_y = ($cell_y - $row_height) + ($content_below_line + $inter_line_spc);
			}
			else {
				$content_offset_y = ($cell_y - $row_height) + $half_em;	
			}
		}

		elsif ($v_align eq "middle") {
			if ($multi_line) {
				my $inter_line_spc = scalar(@lines) * $font_size * $font_size_scale * 0.5;
				my $pre_spc = ($row_height - ($content_height + $inter_line_spc)) / 2;
				$content_offset_y = $cell_y - ($pre_spc + ($font_size * $font_size_scale * 1.5)); 	
			}
			else {
				$content_offset_y = $cell_y - (int(($row_height - $content_height) / 2) + $content_height);
#				$content_offset_y = $cell_y - (($row_height - $content_height) / 2) + $content_height;
			}
		}

		if ($h_align eq "left") {
			$content_offset_x = $cell_x + $half_em;
		}

		elsif ($h_align eq "right") {
			if ($multi_line) {	
				foreach (@lines) {
					my $content_width = guess_width($_);
					$right_x_offsets{$_} =  ($cell_x + $col_width) - ($content_width + $half_em) ;
				}
			}
			else {
				$content_offset_x = ($cell_x + $col_width) - ($content_width + $half_em);
			}
		}

		elsif ($h_align eq "center") {
			if ($multi_line) {	
				foreach (@lines) {
					my $content_width = guess_width($_, $font_size);
					$center_x_offsets{$_} =  $cell_x + int(($col_width - $content_width) / 2);
#					$center_x_offsets{$_} =  $cell_x + (($col_width - $content_width) / 2);
				}
			}
			else {
				$content_offset_x = $cell_x + int (($col_width - $content_width) / 2);
#				$content_offset_x = $cell_x + (($col_width - $content_width) / 2);
			}
		}
		elsif ($h_align eq "justify") {

			unless ($multi_line) {
				push @lines, $cell_content;
			}

			for (my $h = 0; $h < @lines; $h++) {
				my $content_width = guess_width($lines[$h],$font_size);
			
				my $surplus_px = ($col_width - ($font_size * $font_size_scale)) - $content_width;
				my $spaces = int(($surplus_px / ($font_size * $font_size_scale)) * 3.7);
		
				my $content_len = length($lines[$h]);
				my $spaces_per_char = 1;
				my $heisenberg = 1;
				my $surplus = 0;

				if ($spaces > $content_len) {
					$spaces_per_char = int($spaces / $content_len );
					#the spaces will fit precisely into the content
					#unlikely...
					if (($spaces_per_char * $content_len) == $spaces) {
						$heisenberg = 0;
					}
					else {
						$surplus = $spaces - ($spaces_per_char * $content_len);	
					}
				}
	
				my $new_content = "";
				my $brk_pnt = $content_len - 1;
	

				for (my $i = 0; $i < $content_len - 1; $i++) {
					my $char = substr($lines[$h], $i, 1);	
					my $num_spaces = $spaces_per_char;
				
					if ($heisenberg) {
						if ($surplus-- > 0) {
							$num_spaces++;
						}
					}
					#Due to the uncertainty introduced above,
					#ensure you do not overpad
					if (($spaces - $num_spaces) >= 0) {
						my $pre_pend = int ($num_spaces / 2);
						my $a_pend = ($pre_pend * 2) == $num_spaces ? $pre_pend : $pre_pend + 1;
	
						$new_content .= " " x $pre_pend;
						$new_content .= $char;
						$new_content .= " " x $a_pend;
						$spaces -= $num_spaces;
					}
					else {
						$new_content .= $char;
						$brk_pnt = $i + 1;
					}
				}
				#append all remaining spaces
				$new_content .= " " x $spaces;
	
				for (my $j = $brk_pnt; $j < $content_len; $j++) {
					my $char = substr($lines[$h], $j, 1);
					$new_content .= $char;	
				}
				if ($multi_line) {	
					$lines[$h] = $new_content;
				}
				else {
					$cell_content = $new_content;
				}
				$content_offset_x = $cell_x + int(($font_size * $font_size_scale) / 2);
#				$content_offset_x = $cell_x + (($font_size * $font_size_scale) / 2);
			}
		}
		unless ($multi_line) { 	
			$text->translate($content_offset_x, $content_offset_y);
		}
		$text->font($font, $font_size);

		if ($multi_line) {	
			for my $line (@lines) {
				if (keys %center_x_offsets) {
					if (exists $center_x_offsets{$line}) {
						$content_offset_x = $center_x_offsets{$line};
					}
				}
				elsif (keys %right_x_offsets) {
					if (exists $right_x_offsets{$line}) {
						$content_offset_x = $right_x_offsets{$line};
					}
				}
				
				$text->translate($content_offset_x, $content_offset_y);	
				$text->text($line);
				$content_offset_y -= ($font_size * $font_size_scale * 1.5);	
			}
		}
		else {
			$text->text($cell_content);
		}	
		#update co-ord system 
		$cell_x += $col_width;
		
		#reset cell_x to 0
		if ($col >= $no_cols) {	
			$cell_x = $x_offset;
			$cell_y -= $row_height;		
		}
	}
	$graph->stroke();

}

sub cell_ref_sort {
	if ($a =~ /^(\d+),(\d+)$/) {
		my ($a_row,$a_col) =($1,$2);
		if ($b =~ /^(\d+),(\d+)$/) {
			my ($b_row,$b_col) =($1,$2);
			my $row_cmp = $a_row <=> $b_row;
			#when matching within row... 
			if ($row_cmp == 0) {
				return $a_col <=> $b_col;
			}
			else {
				return $row_cmp;
			}
		}
	}
	return 0;	
}

#guess_width(str, font_size)
sub guess_width {
	my $str = shift @_;
	my $font_size = shift @_;
	my $width = 0;	
	for (my $i = 0; $i < length($str); $i++) {
		my $char = substr($str,$i,1);	
		#UC: 0.75	
		if ($char =~ /[A-Z]/) {
			$width += 0.78;	
		}
		#lc: 0.46
		elsif ($char =~ /[a-z]/) {
			$width += 0.50;	
		}
		#numerals: 0.5
		elsif ($char =~ /[0-9]/) {
			$width += 0.54;	
		}
		#punctuation mark?: 0.42
		else {
			$width += 0.46;	
		}
	}
	return int($width * $font_size);
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d{1,2}))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;

}
