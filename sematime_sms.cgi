#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;
#use Storable qw/freeze thaw/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir,$modem_manager1,$sematime_user_id,$sematime_api_key);

my %session;
my %auth_params;

my $logd_in = 0;
my $authd = 0;

my $con;

#used by view inbox/sent messages
#i really should take that advice about simple programs
#connected by clean interfaces.
my $page = 1;
my $per_page = 10;

my %grading;
my %points;
my $rank_partial = 0;
my %rank_by_points;
my $current_yr = (localtime)[5] + 1900;
my $exam_yr = $current_yr;

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
		$logd_in++;
		my $id = $session{"id"};
		if ($id eq "1") {
			$authd++;
		}
	}
	#per page set
	if (exists $session{"per_page"} and $session{"per_page"} =~ /^(\d+)$/) {
		$per_page = $1;
	}
}

my $content = '';
my $feedback = '';
my $js = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/sematime_sms.cgi">Sematime SMS</a>
	<hr> 
};

unless ($authd) {

	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Send Messages</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to send messages.</span> Only the administrator is authorized to take this action.
</body>
</html> 
*;

		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}

	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/message.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Yans: Send Messages</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/message.cgi">/login.html?cont=/cgi-bin/message.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/message.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;
my @datasets;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	
	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}
	unless ($multi_part) {
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
				if ( $k eq "datasets" ) {
					if ($v eq "students" or $v eq "teachers" or $v =~ /^\d+$/) {
						push @datasets, $v;
					}
				}
				else {
					$auth_params{$k} = $v;
				}
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

my $job = undef;
my $act = "";

if ( exists $ENV{"QUERY_STRING"} ) {
	
	if ( $ENV{"QUERY_STRING"} =~ /\&?job=(\d+)\&?/i ) {
		$job = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?act=([^\&]+)\&?/i ) {
		$act = lc($1);
	}
}


PM: {
	#create job
	if ($post_mode) {

		#check conf tokens
		unless ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"} ) {
			$feedback = qq!<p><span style="color: red">No valid confirmation code was sent.</span> Do not alter any of the hidden values in the HTML form.!;	
			$post_mode = 0;
			$act = "";
			last PM;
		}

		#check that the message template contains '<<results>>'
		unless ( exists $auth_params{"message"} and $auth_params{"message"} =~ /<<results>>/ ) {
			$feedback = qq!<span style="color: red">No valid message to send specified.</span> A valid message must contain the string <em>&lt;&lt;results&gt;&gt;</em>.!;
			$post_mode = 0;
			$act = "";
			last PM;
		}

		my $msg_template = $auth_params{"message"};
		
		#job id should have been posted
		unless (defined $job) {
			$feedback = qq!<p><span style="color: red">No valid job id specified.</span> Do not alter any of the values in the URL query string.!;
			$post_mode = 0;
			$act = "";
			last PM;
		}

		#check that the job id requested does not already exist
		my $valid_job_id = 1;
		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

		my $prep_stmt4 = $con->prepare("SELECT messaging_job FROM sematime_outbox WHERE messaging_job=? LIMIT 1");
	
		if ($prep_stmt4) {

			my $rc = $prep_stmt4->execute();

			if ($rc) {
				while ( my @rslts = $prep_stmt4->fetchrow_array() ) {
					if ($rslts[0] =~ /^\d+$/) {
						$valid_job_id = 0;
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM sematime_outbox: ", $con->errstr, $/;
			}

		}
		else {
			print STDERR "Could not prepare SELECT FROM sematime_outbox: ", $con->errstr, $/;
		}
		
		unless ($valid_job_id) {
			$feedback = qq!<p><span style="color: red">No valid job id specified.</span> Do not alter any of the values in the URL query string.!;
			$post_mode = 0;
			$act = "";
			last PM;
		}


		my (@subjects, @classes);

		my $yrs_study = 4;
		my ($min_class, $max_class) = (undef,undef);

		my $exam = undef;	

		my $prep_stmt2 = $con->prepare("SELECT id,value FROM vars WHERE id='1-subjects' OR id='1-classes' OR id='1-exam' OR id='1-grading' OR id='1-rank partial' OR id='1-rank by points' OR id='1-points' LIMIT 7");
	
		if ($prep_stmt2) {

			my $rc = $prep_stmt2->execute();
			if ($rc) {
				while ( my @rslts = $prep_stmt2->fetchrow_array() ) {

					if ($rslts[0] eq "1-subjects") {
						@subjects = split/,/, $rslts[1];
					}
					elsif ($rslts[0] eq "1-classes") {
						@classes = split/,/, $rslts[1];

						foreach (@classes) {
							if ($_ =~ /(\d+)/) {
								my $tst_yr = $1;
								if (not defined $min_class) {
									$min_class = $tst_yr;
									$max_class = $tst_yr;
								}
								else {
									$min_class = $tst_yr if ($tst_yr < $min_class);
									$max_class = $tst_yr if ($tst_yr > $max_class);
								}
							}
							$yrs_study = ($max_class - $min_class) + 1;
						}

					}

					elsif ($rslts[0] eq "1-exam") {
						$exam = $rslts[1];
						if ( $exam =~ /(\d{4})/ ) {
							$exam_yr = $1;
						}
					}

					elsif ($rslts[0] eq "1-grading") {

						my $grading_str = $rslts[1];
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
									#the bugs I picked on accnt of not including tht +/-1!
									${$grading{$grade}}{"min"} = $min -1;
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
					#rank partial
					elsif ($rslts[0] eq "1-rank partial") {
						if (defined $rslts[1] and lc($rslts[1]) eq "no") {
							$rank_partial = 0;
						}
					}

					#rank by points
					elsif ( $rslts[0] eq "1-rank by points" ) {

						if ( defined($rslts[1]) and $rslts[1] =~ /^(?:[0-9]+,?)+$/ ) {
							
							my @yrs = split/,/,$rslts[1];
							for my $yr (@yrs) {
								$rank_by_points{$yr}++;
							}
						}
					}
					#points
					elsif ($rslts[0] eq "1-points") {
						my $points_str = $rslts[1];
						my @points_bts = split/,/,$points_str;
						foreach (@points_bts) {
							if ($_ =~ /^([^:]+):\s*(.+)/) {
								my ($grade,$points) = ($1,$2);
								$points{$grade} = $points;	
							}
						}
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM vars: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM vars: ", $con->errstr, $/;
		}

		#get classes
		my %classes;
		for my $auth_param (keys %auth_params) {
			if ( $auth_param =~ /^class_(.+)$/ ) {

				my $class_field_name = $1;
				my $class = $auth_params{$auth_param};

				if ( $class_field_name eq $class ) {
					$classes{$class}++;
				}
			}
		}

		my %recipients = ();
		my %stud_lookup = ();
		my %class_lookup = ();

		#read student_rolls

		my $prep_stmt5 = $con->prepare("SELECT table_name,upper(class),start_year FROM student_rolls WHERE grad_year >= ?");
	
		if ($prep_stmt5) {

			my $rc = $prep_stmt5->execute($current_yr);

			if ($rc) {

				while ( my @rslts = $prep_stmt5->fetchrow_array() ) {

					my $class = $rslts[1];
					my $yr = ( $current_yr - $rslts[2] ) + 1;

					$class =~ s/\d+/$yr/;

					if ( exists $classes{$class} ) {

						$classes{$class} = $rslts[0];
						$class_lookup{$class} = {"table" => $rslts[0], "start_year" => $rslts[2]};

					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM student_rolls: ", $con->errstr, $/;
			}

		}
		else {
			print STDERR "Could not prepare SELECT FROM student_rolls: ", $con->errstr, $/;
		}


		#read adms
		if (scalar(values %classes) > 0 ) {
	
			my @where_clause_bts = ();
			foreach (values %classes) {
				push @where_clause_bts, "table_name=?";
			}
			my $where_clause = join(" OR ", @where_clause_bts);

			#my $num_rows = scalar(@where_clause_bts);

			#read student tables
			my $prep_stmt5 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE $where_clause");
	
			if ($prep_stmt5) {

				my $rc = $prep_stmt5->execute(values(%classes));
				if ($rc) {
					while ( my @rslts = $prep_stmt5->fetchrow_array() ) {
						$recipients{$rslts[0]} = $msg_template;
						$stud_lookup{$rslts[0]} = $rslts[1];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM adms: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM adms: ", $con->errstr, $/;
			}

		}

		else {
			$feedback = qq!<p><span style="color: red">No classes were selected.</span> You must select atleast 1 class to send SMS to.!;	
			$post_mode = 0;
			$act = "";
			last PM;
		}
		#convert class->tables lookup to yr->tables lookup
		my %tables;
		for my $class (keys %class_lookup) {

			my $table = ${$class_lookup{$class}}{"table"};
			my $yr = ${$class_lookup{$class}}{"start_year"};

			${$tables{$yr}}{$table}++;
		}

		my %requested_tables;

		for my $stud ( keys %stud_lookup ) {

			my $tbl = $stud_lookup{$stud};
			$requested_tables{$tbl}++;

		}

		#chuck any unrepresented 
		for my $start_yr ( keys %tables ) {
	
			my @tables_arr = keys %{$tables{$start_yr}};
						
			my $repd = 0;

			foreach (@tables_arr) {
				if (exists $requested_tables{$_}) {
					$repd++;
					last;
				}
			}

			delete $tables{$start_yr} if (not $repd);
		}

		my %subject_short_forms = ("english" => "Eng", "kiswahili" => "Kisw", "physics" => "Phy", "mathematics" => "Math", "chemistry" => "Chem", "biology" => "Bio", "agriculture" => "Agric", "geography" => "Geog", "computers" => "Comps", "history" => "Hist", "home science" => "H/Sci", "business studies" => "B/S");

		for my $start_year ( keys %tables ) {

						
			my %class_sizes = ();
			my $yr_size = 0;

			my %stud_rolls;	
			my @tables_arr = keys %{$tables{$start_year}};

			my %stud_subjects = ();
			#need to reset for every class
			$yr_size = 0;

			for my $table ( @tables_arr ) {
							
				my $prep_stmt5 = $con->prepare("SELECT adm,subjects FROM `$table`");

				if ($prep_stmt5) {

					my $rc = $prep_stmt5->execute();
					if ($rc) {
						while (my @rslts = $prep_stmt5->fetchrow_array()) {

							my @subjs = split/,/,$rslts[1];
							for my $subj (@subjs) {
								$stud_subjects{$rslts[0]}->{$subj}++;
							}

							$class_sizes{$table}++;
							$yr_size++;
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM $table statement: ", $prep_stmt5->errstr, $/;
					}

				}
				else {
					print STDERR "Could not prepare SELECT FROM $table statement: ", $prep_stmt5->errstr, $/;
				}

			}

			my @where_clause_bts = ();

			foreach ( @tables_arr ) {
				push @where_clause_bts, "roll=?";
			}

			my $where_clause = join(' OR ', @where_clause_bts);

	      		my $prep_stmt4 = $con->prepare("SELECT table_name,roll,subject FROM marksheets WHERE exam_name=? AND ($where_clause)");

			if ($prep_stmt4) {

				my $rc = $prep_stmt4->execute($exam, @tables_arr);

				if ($rc) {

					while (my @rslts = $prep_stmt4->fetchrow_array()) {
						${$stud_rolls{$rslts[1]}}{$rslts[2]} = $rslts[0];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt4->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt4->errstr, $/;
			}

			my %tables_hash;
			@tables_hash{@tables_arr} = @tables_arr;

			my %student_data = ();

			for my $stud ( keys %stud_lookup ) {

				my $tbl = $stud_lookup{$stud};
				next unless exists $tables_hash{$tbl};

				$student_data{$stud} = 
				{	
				"total" => 0,
				"subject_count" => 0,
				"avg" => -1,
				"points_avg" => -1,
				"mean_grade" => "-",
				"class_rank" => 1,
				"overall_rank" => 1,
				};

				#preset the values of subjects to N/A
				foreach ( keys %{$stud_subjects{$stud}} ) {
					${$student_data{$stud}}{"subject_$_"} = "N/A";
					${$student_data{$stud}}{"grade_subject_$_"} = "-";
				}
			}
	

			#read the marksheets in DB:-
			#for each marksheet, update student_data	
			#in the switch from F2-F3 the student's
			#'subjects' records are changed
			#RULE: assume subjects can be removed but not
			#added. Therefore, any missing records in the 
			#{"subjects"} field are N/A
			#any additional values however, are allowed
						
			for my $stud_roll (keys %stud_rolls) {

				for my $subject (keys %{$stud_rolls{$stud_roll}}) {
									
					my $marksheet =  ${$stud_rolls{$stud_roll}}{$subject};
									
					my $prep_stmt5 = $con->prepare("SELECT adm,marks FROM `$marksheet`");
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
						print STDERR "Could not prepare SELECT FROM $marksheet statement: ", $prep_stmt5->errstr, $/;
					}

					for my $stud_adm (keys %marksheet_data) {
									
 						${$student_data{$stud_adm}}{"subject_$subject"} = $marksheet_data{$stud_adm};

						my $grade = get_grade($marksheet_data{$stud_adm});		
						${$student_data{$stud_adm}}{"grade_subject_$subject"} = $grade;
					
						#increment the subject count
						#if doing a partial rank
						#just realized that 'partial rank'
						#doesn't capture the idea behind the name
						if ( $rank_partial or not exists $stud_subjects{$stud_adm}->{$subject} ) {
							${$student_data{$stud_adm}}{"subject_count"}++;
						}
						else {
							${$student_data{$stud_adm}}{"subject_count"} = scalar(keys %{$stud_subjects{$stud_adm}});
						}
						
						${$student_data{$stud_adm}}{"total"} += $marksheet_data{$stud_adm};	

						my $points = $points{$grade};
						${$student_data{$stud_adm}}{"points_total"} += $points;

						${$student_data{$stud_adm}}{"avg"} = ${$student_data{$stud_adm}}{"total"} / ${$student_data{$stud_adm}}{"subject_count"};
						${$student_data{$stud_adm}}{"points_avg"} = ${$student_data{$stud_adm}}{"points_total"} / ${$student_data{$stud_adm}}{"subject_count"};
									
						${$student_data{$stud_adm}}{"mean_grade"} = get_grade(${$student_data{$stud_adm}}{"avg"});
								
					}
				}
			}

			my %class_rank_cntr = ();

			foreach (keys %stud_rolls) {	
				$class_rank_cntr{$_} = 0;	
			}

			my $overall_cntr = 0;

			my $sort_by = "avg";

			my $stud_yr = ($exam_yr - $start_year) + 1;

			if ( exists $rank_by_points{$stud_yr} ) {
				$sort_by = "points_avg";
			}

			for my $stud (sort { ${$student_data{$b}}{$sort_by} <=> ${$student_data{$a}}{$sort_by} } keys %student_data) {

				${$student_data{$stud}}{"overall_rank"} = ++$overall_cntr;
				my $class = $stud_lookup{$stud};

				${$student_data{$stud}}{"class_rank"} = ++$class_rank_cntr{$class};	
			}
	
			my $prev_rank = -1;
			my $prev_avg = -1;

			#deal with ties within class
			for my $stud_2 (sort { ${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {
				my $current_rank = ${$student_data{$stud_2}}{"overall_rank"};
				my $current_avg = ${$student_data{$stud_2}}{$sort_by};
		
				if ($prev_avg == $current_avg) {
					${$student_data{$stud_2}}{"overall_rank"} = $prev_rank;	
				}
						
				$prev_rank = ${$student_data{$stud_2}}{"overall_rank"};
				$prev_avg  = $current_avg;
			}

			my %class_rank_cursor = ();

			foreach (keys %stud_rolls) {	
				$class_rank_cursor{$_} = {"prev_rank" => -1, "prev_avg" => -1};
			}

			for my $stud_3 (sort {${$student_data{$a}}{"overall_rank"} <=> ${$student_data{$b}}{"overall_rank"} } keys %student_data) {

				my $class = $stud_lookup{$stud_3};
				
				my $current_rank = ${$student_data{$stud_3}}{"class_rank"};
				my $current_avg = ${$student_data{$stud_3}}{$sort_by};
								
				if (${$class_rank_cursor{$class}}{"prev_avg"} == $current_avg) {
					${$student_data{$stud_3}}{"class_rank"} = ${$class_rank_cursor{$class}}{"prev_rank"};
				}
							
				${$class_rank_cursor{$class}}{"prev_rank"} = ${$student_data{$stud_3}}{"class_rank"};
				${$class_rank_cursor{$class}}{"prev_avg"}  = $current_avg;
			}

						
			for my $recipient (keys %recipients) {
				my $tbl = $stud_lookup{$recipient};
				#here be dragons--had a bug: wld replace
				#all '<<students.results>>' fields with 'N/A'
				#after the 1st class was processed.
							
				next unless (exists $tables_hash{$tbl});

				my $results = "N/A";

				if (exists $student_data{$recipient}) {

					my %data = %{$student_data{$recipient}};
					my $table = $stud_lookup{$recipient};

					my @subjects_results = ();

					for my $data_elem (sort {$a cmp $b} keys %data) {
						if ($data_elem =~ /^subject_(.+)/) {

							next if ($data_elem eq "subject_count");

							my $subj = $1;
							my $subj_short_form = $subj;

							if ( exists $subject_short_forms{lc($subj)} ) {

								$subj_short_form = $subject_short_forms{lc($subj)};

							}

							my $score = $data{$data_elem};
							my $grade = $data{"grade_subject_$subj"};
	
							push @subjects_results, "$subj_short_form: $score($grade)";
						}
					}

					my $results_str = "Adm no: $recipient." . join("  ", @subjects_results);

					$results_str .= ". Avg: " . sprintf("%.2f", $data{"avg"}) . "(" . $data{"mean_grade"} . ")"; 
					$results_str .= ". Class Pos: " . $data{"class_rank"}   . " of " . $class_sizes{$table};
					$results_str .= ". Overall Pos: " . $data{"overall_rank"} . " of " . $yr_size;
						
					$results = $results_str;
				}

				$recipients{$recipient} =~ s/<<results>>/$results/g;
				#print "X-Debug-$recipient: $recipients{$recipient}\r\n";

			}
		}

		my %contacts = ();

		my $prep_stmt8 = $con->prepare("SELECT id,phone_no FROM contacts WHERE phone_no IS NOT NULL");
	
		if ($prep_stmt8) {
			my $rc = $prep_stmt8->execute();
			if ($rc) {
				while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
					$contacts{$rslts[0]} = $rslts[1];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM contacts: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM contacts: ", $con->errstr, $/;
		}

		#write to sematime_outbox
		my $prep_stmt6 = $con->prepare("INSERT INTO sematime_outbox VALUES(NULL,$job,?,?,'',1,0)");

		if ($prep_stmt6) {

			for my $recipient ( sort {$b <=> $a} keys %recipients ) {

				
				next unless (exists $contacts{$recipient});

				#had forgotten that the 'phone_no' field is a comma-delimited list
				my @recipient_contacts = split/,/,$contacts{$recipient};

				for my $recipient_contact (@recipient_contacts) {

					my $rc = $prep_stmt6->execute($recipient_contact, $recipients{$recipient});

					unless ($rc) {
						print STDERR "Could not prepare INSERT INTO sematime_outbox: ", $con->errstr, $/;
					}

				}

			}

		}
		else {
			print STDERR "Could not prepare INSERT INTO sematime_outbox: ", $con->errstr, $/;
		}


		#$post_mode = 0;$act = "";
		$con->commit();

		#log create job	
		my @today = localtime;	
		my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							
		open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

	      	if ($log_f) {

       			@today = localtime;	
			my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
			flock ($log_f, LOCK_EX) or print STDERR "Could not log create sematime sms job: $!$/";
			seek ($log_f, 0, SEEK_END);
									
			print $log_f "1 CREATE SEMATIME.COM MESSAGING JOB $job $time\n";	

			flock ($log_f, LOCK_UN);
       			close $log_f;

       		}
		else {
			print STDERR "Could not log create sematime.com messaging job for 1: $!\n";
		}

		#launch child to do actual sending
		my $pid = fork;
		#child
		if ($pid == 0) {

			use POSIX;

			close STDIN;
			close STDOUT;
			close STDERR;

			POSIX::setsid();

			exec "perl", "/usr/local/bin/sematime_sms_send.pl", $job;
			exit 0;

		}
		#parent
		else {
			$SIG{CHLD} = 'IGNORE';
		}
	}
}

if (not $post_mode) {

	#reread DB send
	if ($act eq "refresh") {

		$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>

<META http-equiv="Refresh" content="10; url=/cgi-bin/sematime_sms.cgi?job=$job&act=refresh">
<title>Messenger - Send Messages - Send Message</title>
</head>

<body>

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/cgi-bin/sematime_sms.cgi">Sematime.com results SMS</a>

<hr>
*;
		my $msgs = 
qq!
<TABLE border="1">
<THEAD>
<TH>Recipient<TH>Text<TH>Status
</THEAD>
<TBODY>
!;
		my $msg_count = 0;

		#read db
		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

		my ($min,$max,$sent) = (0,0,0);

		my $prep_stmt7 = $con->prepare("SELECT recipient,text,status,sent FROM sematime_outbox WHERE messaging_job=? ORDER BY message_id ASC");

		if ($prep_stmt7) {

			my $rc = $prep_stmt7->execute($job);

			if ($rc) {

				while ( my @rslts = $prep_stmt7->fetchrow_array() ) {

					$msg_count++;

					my $text = htmlspecialchars($rslts[1]);

					my $status_color = "black";
					my $status = "Pending";

					#failed
					if ($rslts[2] == 0) {
						$status_color = "red";
						$status = "Failed";					
					}

					elsif ( $rslts[2] == 2 ) {
						$status_color =  "green";
						$status = "Sent&nbsp;" . custom_time($rslts[3]);
						
						if ($min == 0) {
							$min = $rslts[2];
						}
						if ($rslts[2] > $max) {
							$max = $rslts[2];
						}
						if ($rslts[2] < $min) {
							$min = $rslts[2];
						}
						$sent++;
					}
				
					$msgs .= qq!<TR><TD>$rslts[0]<TD>$text<TD style="color: $status_color">$status!;

				}

			}

			else {
				print STDERR "Could not execute SELECT FROM sematime_outbox: ", $con->errstr, $/;
			}

		}
		else {
			print STDERR "Could not prepare SELECT FROM sematime_outbox: ", $con->errstr, $/;
		}

		if ($msg_count > 0) {
			$msgs .= "</TBODY></TABLE>";
		}
		else {
			$msgs = "<em>Sorry. There are no messages to display.</em> Perhaps there's no such job or there're no contact details associated with the students selected.";
		}

		my $percent_sent = "0%";
		my $send_rate = "Unknown";
		my $estimated_time_remaining = "Unknown";
		my $last_activity = "None";

		#more than 1 sms sent
		if ($sent > 1 and $msg_count > 0 and $min != $max) {

			$percent_sent = sprintf("%.1f%", ($sent / $msg_count));

			my $rate = sprintf("%.1f", (60 / ( ($max - $min) / $sent )) );
			my $send_rate = qq!$rate SMSs/min!;

			my $remaining_time = 0;
			if ( $rate > 0 ) {
				$remaining_time = sprintf( "%.1f", ($msg_count - $sent) / $rate );
			}

			my $estimated_time_remaining = qq!$remaining_time mins!;
			
			$last_activity = custom_time($max);

		}
	
		my $progress_summary = qq*

<TABLE style="text-align: left">
<TR><TH>Percent Sent<TD>$percent_sent
<TR><TH>Send Rate<TD>$send_rate
<TR><TH>Estimated Time Remaining<TD>$estimated_time_remaining
<TR><TH>Last Activity<TD>$last_activity
</TABLE>
*;	
		$content .= qq!${progress_summary}<HR>${msgs}</body></html>!;
	}

	#show send interface
	else {

		#read classes
		my @classes = ("1", "2", "3", "4");

	
		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

		my $prep_stmt2 = $con->prepare("SELECT id,value FROM vars WHERE id='1-classes' LIMIT 1");
	
		if ($prep_stmt2) {

			my $rc = $prep_stmt2->execute();

			if ($rc) {
				while ( my @rslts = $prep_stmt2->fetchrow_array() ) {	
					if ($rslts[0] eq "1-classes") {
						@classes = split/,/, uc($rslts[1]);
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM vars: ", $con->errstr, $/;
			}

		}
		else {
			print STDERR "Could not prepare SELECT FROM vars: ", $con->errstr, $/;
		}			

		my $job_id = 0;
		my $prep_stmt3 = $con->prepare("SELECT max(messaging_job) FROM sematime_outbox LIMIT 1");
	
		if ($prep_stmt3) {

			my $rc = $prep_stmt3->execute();

			if ($rc) {
				while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
					if ( defined $rslts[0] and $rslts[0] =~ /^\d+$/ ) {
						$job_id = $rslts[0];
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM sematime_outbox: ", $con->errstr, $/;
			}

		}
		else {
			print STDERR "Could not prepare SELECT FROM sematime_outbox: ", $con->errstr, $/;
		}

		$job_id++;

		my $classes_select = "";
		my $current_yr = undef;

		for my $class (sort {$a cmp $b} @classes) {
			my $class_yr = "";
			if ( $class =~ /(\d+)/ ) {
				$class_yr = $1;
			}

			if (defined $current_yr and $class_yr ne $current_yr) {
				$classes_select .= "<BR>";
			}
			$classes_select .= qq!<INPUT type="checkbox" name="class_$class" value="$class" checked="1">$class&nbsp;&nbsp;&nbsp;!;
			$current_yr = $class_yr;
		}

		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Messenger - Send Messages - Send Message</title>
</head>

<body>

<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/cgi-bin/sematime_sms.cgi">Sematime.com results SMS</a>

<hr>
$feedback
<FORM method="POST" action="/cgi-bin/sematime_sms.cgi?act=refresh&job=$job_id">

<TABLE>

<TR><TD><LABEL for="recipient">Classes</LABEL><TD>&nbsp;$classes_select
<TR><TD><LABEL for="message">Message</LABEL><TD><TEXTAREA name="message" cols="30" rows="6"></TEXTAREA>
<TR><TD>&nbsp;<TD><em>&lt;&lt;results&gt;&gt; will be automatically replaced with the students results.</em>
<TR><TD colspan="2"><INPUT type="submit" name="send" value="Send">

</TABLE>

<INPUT type="hidden" name="confirm_code" value="$conf_code">

</FORM>

</body>
</html>
*;
	}

}

print "Status: 200 OK\r\n";

if ($act eq "refresh") {
	print "Refresh: 10; url=/cgi-bin/sematime_sms.cgi?job=$job&act=refresh\r\n";
}

print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

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

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
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
	my $grade = "";
	return "" unless (@_);
	my $score = $_[0];

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

sub custom_time {

	my $custom_time = "";

	my $time = $_[0];
	my $now = time;
	
	my $elapsed_time = $now - $time;
	
	#-ve elapsed time? this shouldn't happen...
	#but just being careful.
	#if less than a day has elapsed,
	#just give the minutes/secs/hrs passed
	if ( $elapsed_time >= 0 and $elapsed_time < 86400) {
		#seconds
		if ( $elapsed_time < 60 ) {
			$custom_time .= $elapsed_time . " sec ago";
		}
		#minutes
		elsif ( $elapsed_time < 3600 ) {

			my $minutes = int($elapsed_time / 60);
			my $seconds = $elapsed_time - ($minutes * 60);
	
			$custom_time .= $minutes ." min";

			if ($seconds > 0) {
				$custom_time .= ", " . $seconds . " sec";
			}
			$custom_time .= " ago";
		}
		#an hr+
		else {
			my $hrs = int ($elapsed_time / 3600);
			$elapsed_time -= ($hrs * 3600);

			my $minutes = int($elapsed_time / 60);
				
			$custom_time .= $hrs . ($hrs == 1 ? " hr" : " hrs");

			if ($minutes > 0) {
				$custom_time .= ", " . $minutes . " min";
			}
			
			$custom_time .= " ago";
		}
	}

	else {
		my @time_bts = localtime($time);

		$custom_time = sprintf ("%02d/%02d/%d %02d:%02d:%02d", $time_bts[3], ($time_bts[4] + 1), ($time_bts[5] + 1900),  $time_bts[2], $time_bts[1], $time_bts[0]);
	}
	return $custom_time;
}
